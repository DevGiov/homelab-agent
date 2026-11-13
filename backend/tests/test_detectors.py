"""Test per i rilevatori di sensibilità dei dati (detectors.py).

Verifiche su valori inventati conformi agli algoritmi ufficiali (IBAN mod 97, Codice Fiscale, Luhn),
casi limite negativi, redazione dei segreti ed elevazione delle etichette.
"""
from app.security.detectors import (
    label_for,
    redact_secrets,
    scan,
    tag_for,
)
from app.security.flows import PUBLIC_TAG, Label


def _calculate_cf_cin(prefix15: str) -> str:
    """Calcola il carattere di controllo (CIN) per 15 caratteri di Codice Fiscale."""
    odd_map = {
        "0": 1, "1": 0, "2": 5, "3": 7, "4": 9, "5": 13, "6": 15, "7": 17, "8": 19, "9": 21,
        "A": 1, "B": 0, "C": 5, "D": 7, "E": 9, "F": 13, "G": 15, "H": 17, "I": 19, "J": 21,
        "K": 2, "L": 4, "M": 18, "N": 20, "O": 11, "P": 3, "Q": 6, "R": 8, "S": 12, "T": 14,
        "U": 16, "V": 10, "W": 22, "X": 25, "Y": 24, "Z": 23,
    }
    even_map = {
        "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
        "A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5, "G": 6, "H": 7, "I": 8, "J": 9,
        "K": 10, "L": 11, "M": 12, "N": 13, "O": 14, "P": 15, "Q": 16, "R": 17, "S": 18, "T": 19,
        "U": 20, "V": 21, "W": 22, "X": 23, "Y": 24, "Z": 25,
    }
    prefix = prefix15.upper()
    tot = sum(odd_map[prefix[i]] if i % 2 == 0 else even_map[prefix[i]] for i in range(15))
    return chr(ord("A") + (tot % 26))


def _make_valid_iban(country: str, bban: str) -> str:
    """Calcola un IBAN valido con algoritmo ISO 7064 Mod 97-10."""
    temp = bban.upper() + country.upper() + "00"
    num_str = "".join(str(ord(c) - 55) if c.isalpha() else c for c in temp)
    remainder = int(num_str) % 97
    check_digits = f"{98 - remainder:02d}"
    return f"{country.upper()}{check_digits}{bban.upper()}"


# --- Test Secret -----------------------------------------------------------------------------------

def test_secret_pem_private_key():
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA0Y1inventedkeydataherefakecontentfakecontentfake\n"
        "-----END RSA PRIVATE KEY-----"
    )
    text = f"Ecco la chiave:\n{pem}\nNon condividerla."
    findings = scan(text)
    secrets = [f for f in findings if f.kind == "secret"]
    assert len(secrets) == 1
    assert secrets[0].label == Label.SECRET
    assert text[secrets[0].start:secrets[0].end] == pem


def test_secret_known_token_prefixes():
    tokens = [
        "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
        "gho_1234567890abcdefghijklmnopqrstuvwxyz",
        "ghs_1234567890abcdefghijklmnopqrstuvwxyz",
        "github_pat_11AAAAAAA01234567890_abcdefghijklmnopqrstuvwxyz1234567890",
        "glpat-abcdef1234567890test",
        "sk-ant-api03-abcdef1234567890abcdef",
        "sk-proj-abcdef1234567890abcdef",
        "sk-12345678901234567890",
        "xoxb-1234567890-1234567890-abcdef123456",
        "xoxp-1234567890-1234567890-abcdef123456",
        "AKIAIOSFODNN7EXAMPLE",
        "AIzaSyD-1234567890123456789012345678901",
        "hf_1234567890abcdef1234567890abcdef",
    ]
    for tok in tokens:
        text = f"Token di test: {tok} configurato."
        findings = [f for f in scan(text) if f.kind == "secret"]
        assert len(findings) == 1, f"Token non rilevato: {tok}"
        assert text[findings[0].start:findings[0].end] == tok


def test_secret_token_negative_near_misses():
    # sk- con meno di 20 caratteri alfanumerici
    text_short_sk = "Prefisso sk-breve123 non valido come chiave"
    assert not any(f.kind == "secret" for f in scan(text_short_sk))

    # AKIA con 15 caratteri anziché 16
    text_short_akia = "AKIA123456789012345"
    assert not any(f.kind == "secret" for f in scan(text_short_akia))

    # AIza con meno di 35 caratteri
    text_short_aiza = "AIza1234567890"
    assert not any(f.kind == "secret" for f in scan(text_short_aiza))

    # hf_ con meno di 30 caratteri
    text_short_hf = "hf_1234567890"
    assert not any(f.kind == "secret" for f in scan(text_short_hf))


def test_secret_jwt():
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J_wStPnS-m_m_m_m"
    text = f"Header Authorization con jwt: {jwt}"
    findings = [f for f in scan(text) if f.kind == "secret"]
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == jwt


def test_secret_key_value_pairs():
    cases = [
        ("password=inventedpassword123", "inventedpassword123"),
        ("passwd: inventedsecret456", "inventedsecret456"),
        ("pwd=mysecretpwd999", "mysecretpwd999"),
        ("token: secret_token_value", "secret_token_value"),
        ("secret=supersecretvalue1", "supersecretvalue1"),
        ("api_key=myapikeyval12345", "myapikeyval12345"),
        ("apikey: myapikeyval12345", "myapikeyval12345"),
        ("access_key=myaccesskey9876", "myaccesskey9876"),
        ("Authorization: Bearer mybearertoken12345", "mybearertoken12345"),
        ("Authorization:Bearer mybearertoken12345", "mybearertoken12345"),
        ("Authorization=Bearer mybearertoken12345", "mybearertoken12345"),
        ('password="quotedpassword123"', "quotedpassword123"),
        ("password='singlequoted123'", "singlequoted123"),
    ]
    for raw, expected_val in cases:
        findings = [f for f in scan(f"Impostato {raw} nel file") if f.kind == "secret"]
        assert len(findings) == 1, f"Fallito per {raw}"
        # Lo span deve essere SOLO il valore
        matched = f"Impostato {raw} nel file"[findings[0].start:findings[0].end]
        assert matched == expected_val, f"Atteso {expected_val!r}, ottenuto {matched!r}"


def test_secret_key_value_negative():
    # Valore più corto di 8 caratteri
    text = "password=short pwd: 1234 token=abc"
    assert not any(f.kind == "secret" for f in scan(text))


# --- Test IBAN -------------------------------------------------------------------------------------

def test_iban_positive():
    # IBAN di esempio pubblico GB
    text_gb = "IBAN pubblico GB82 WEST 1234 5698 7654 32 per accredito"
    f_gb = [f for f in scan(text_gb) if f.kind == "iban"]
    assert len(f_gb) == 1
    assert f_gb[0].label == Label.PRIVATE
    assert text_gb[f_gb[0].start:f_gb[0].end] == "GB82 WEST 1234 5698 7654 32"

    # IBAN calcolato con algoritmo mod 97
    valid_it = _make_valid_iban("IT", "X0542811101000000123456")
    text_it = f"Invia a {valid_it}"
    f_it = [f for f in scan(text_it) if f.kind == "iban"]
    assert len(f_it) == 1
    assert text_it[f_it[0].start:f_it[0].end] == valid_it


def test_iban_negative():
    # Controllo mod 97 errato (GB83 anziché GB82)
    text_wrong_check = "IBAN errato GB83 WEST 1234 5698 7654 32 scartato"
    assert not any(f.kind == "iban" for f in scan(text_wrong_check))


# --- Test Codice Fiscale ---------------------------------------------------------------------------

def test_codice_fiscale_positive():
    # Calcolo del CIN ufficiale nel test
    prefix = "RSSMRA85M01H501"
    cin = _calculate_cf_cin(prefix)
    cf = f"{prefix}{cin}"
    assert cin == "Q"  # Verifica dell'algoritmo su Mario Rossi nato l'01/08/1985

    text = f"Codice fiscale del titolare: {cf}"
    findings = [f for f in scan(text) if f.kind == "codice_fiscale"]
    assert len(findings) == 1
    assert findings[0].label == Label.PRIVATE
    assert text[findings[0].start:findings[0].end] == cf

    # Minuscolo
    text_lower = f"cf: {cf.lower()}"
    findings_lower = [f for f in scan(text_lower) if f.kind == "codice_fiscale"]
    assert len(findings_lower) == 1


def test_codice_fiscale_negative():
    # Carattere di controllo errato
    prefix = "RSSMRA85M01H501"
    wrong_cf = f"{prefix}Z"
    assert not any(f.kind == "codice_fiscale" for f in scan(f"CF errato: {wrong_cf}"))

    # Parole casuali
    assert not any(f.kind == "codice_fiscale" for f in scan("ABCDEF12G34H567Z non valido"))


# --- Test Carte di Credito -------------------------------------------------------------------------

def test_card_positive():
    card = "4111 1111 1111 1111"
    text = f"Numero carta di prova: {card}"
    findings = [f for f in scan(text) if f.kind == "card"]
    assert len(findings) == 1
    assert findings[0].label == Label.PRIVATE
    assert text[findings[0].start:findings[0].end] == card

    # Con trattini
    card_hyphen = "4111-1111-1111-1111"
    findings_hyphen = [f for f in scan(f"Carta: {card_hyphen}") if f.kind == "card"]
    assert len(findings_hyphen) == 1


def test_card_negative_luhn():
    # Fallisce Luhn (cifra finale 2 anziché 1)
    card_invalid = "4111 1111 1111 1112"
    assert not any(f.kind == "card" for f in scan(f"Carta: {card_invalid}"))


# --- Test Telefono ---------------------------------------------------------------------------------

def test_phone_positive():
    cases = [
        "+39 340 1234567",
        "+393401234567",
        "0039 340 1234567",
        "340 1234567",
        "347123456",
        "+1 555 123 4567",
    ]
    for ph in cases:
        text = f"Contattare il numero {ph} per info"
        findings = [f for f in scan(text) if f.kind == "phone"]
        assert len(findings) == 1, f"Telefono non rilevato: {ph}"
        assert findings[0].label == Label.PRIVATE
        assert text[findings[0].start:findings[0].end] == ph


def test_phone_negative_near_misses():
    negatives = [
        "Anno 2026",
        "Porta 8080",
        "Orario 10:30",
        "Versione 1.2.3 rilasciata",
        "192.168.1.10 non è un telefono",
        "ID breve 12345",
        "ID 312345678901",  # 12 cifre, non un cellulare italiano a 9-10 cifre
    ]
    for neg in negatives:
        findings = [f for f in scan(neg) if f.kind == "phone"]
        assert not findings, f"Falso positivo telefono su: {neg}"


# --- Test Email ------------------------------------------------------------------------------------

def test_email_positive():
    text = "Scrivi a utente.test@example.org per assistenza"
    findings = [f for f in scan(text) if f.kind == "email"]
    assert len(findings) == 1
    assert findings[0].label == Label.PRIVATE
    assert text[findings[0].start:findings[0].end] == "utente.test@example.org"


def test_email_negative():
    text = "Non è una email: utente@ oppure @example.org"
    assert not any(f.kind == "email" for f in scan(text))


# --- Test Persona ----------------------------------------------------------------------------------

def test_person_names():
    text = "Ada e adamo sono colleghi, mentre ada lavora da sola."
    # Deve trovare 'Ada' e 'ada', ma non 'adamo'. I nomi < 3 caratteri ('Al') vengono ignorati.
    findings = scan(text, person_names=["Ada", "Al"])
    persons = [f for f in findings if f.kind == "person"]
    assert len(persons) == 2
    assert all(p.label == Label.PRIVATE for p in persons)
    matched_names = [text[p.start:p.end] for p in persons]
    assert matched_names == ["Ada", "ada"]


# --- Test Indirizzi Interni ------------------------------------------------------------------------

def test_internal_address_positive():
    cases = [
        "192.168.1.10",
        "10.0.0.1",
        "127.0.0.1",
        "169.254.1.1",
        "router.lan",
        "server.local",
        "service.internal",
        "nas.home.arpa",
        "box.localdomain",
    ]
    for addr in cases:
        text = f"Host interno: {addr} raggiungibile"
        findings = [f for f in scan(text) if f.kind == "internal_address"]
        assert len(findings) == 1, f"Indirizzo interno non rilevato: {addr}"
        assert findings[0].label == Label.INTERNAL
        assert text[findings[0].start:findings[0].end] == addr


def test_internal_address_negative():
    # 8.8.8.8 è un IP pubblico, non un indirizzo interno
    text = "8.8.8.8 non è internal_address"
    assert not any(f.kind == "internal_address" for f in scan(text))

    # Host pubblico
    text_pub = "Server api.example.org pubblico"
    assert not any(f.kind == "internal_address" for f in scan(text_pub))


# --- Test Redact Secrets ---------------------------------------------------------------------------

def test_redact_secrets():
    text = (
        "Configurazione server:\n"
        "host=192.168.1.10\n"
        "password=supersecretpassword123\n"
        "token: ghp_1234567890abcdefghijklmnopqrstuvwxyz\n"
        "Authorization: Bearer mybearertokenvalue123\n"
        "FINE"
    )
    redacted, count = redact_secrets(text)
    assert count == 3
    # Le chiavi e il resto del testo devono restare intatti
    assert "password=[RIMOSSO: segreto]" in redacted
    assert "token: [RIMOSSO: segreto]" in redacted
    assert "Authorization: Bearer [RIMOSSO: segreto]" in redacted
    assert "host=192.168.1.10" in redacted
    assert "FINE" in redacted
    assert "supersecretpassword123" not in redacted
    assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz" not in redacted


def test_redact_secrets_clean_text():
    text = "Testo completamente pulito senza segreti."
    redacted, count = redact_secrets(text)
    assert count == 0
    assert redacted == text


# --- Test label_for e tag_for ----------------------------------------------------------------------

def test_label_for_multiple_types_highest_label():
    # Combina internal_address (INTERNAL), email (PRIVATE) e password (SECRET)
    text = "Host router.lan notifica admin@example.org con password=supersecretpass12"
    label, kinds = label_for(text)
    assert label == Label.SECRET
    assert kinds == ["email", "internal_address", "secret"]

    # Senza secret, vince PRIVATE
    text_priv = "Host router.lan notifica admin@example.org"
    label_priv, kinds_priv = label_for(text_priv)
    assert label_priv == Label.PRIVATE
    assert kinds_priv == ["email", "internal_address"]


def test_label_for_clean_text():
    label, kinds = label_for("Testo senza alcuna informazione sensibile.")
    assert label == Label.PUBLIC
    assert kinds == []


def test_tag_for_clean_text():
    tag = tag_for("Testo pulito.", "rilevatore")
    assert tag == PUBLIC_TAG


def test_tag_for_detected_data():
    text = "IBAN GB82 WEST 1234 5698 7654 32 e email admin@example.org"
    tag = tag_for(text, "rilevatore")
    assert tag.label == Label.PRIVATE
    assert not tag.untrusted
    assert tag.reasons == ("rilevatore:email", "rilevatore:iban")
