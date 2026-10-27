"""Template e dati tra gli step delle automazioni.

Rendering dei placeholder (`{{steps.id.output}}`, `{{inputs.key}}`, `{{date}}`…), estrazione del
contenuto prodotto da uno step (feed Atom/RSS compattati in testo) e risoluzione dei parametri.
"""
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("automations.templating")


def render_template(template_str: str, context: Dict[str, Any]) -> str:
    """Sostituisce espressioni tipo {{steps.step_id.output}}, {{inputs.key}}, {{config.key}}, {{date}} con fallback fuzzy."""
    if not template_str or not isinstance(template_str, str):
        return template_str

    result = template_str

    # Risoluzione variabili di sistema
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    result = result.replace("{{date}}", today_str)
    result = result.replace("{{datetime}}", now_utc.isoformat())
    result = result.replace("{{run_id}}", str(context.get("run_id", "")))
    result = result.replace("{{automation_id}}", str(context.get("automation_id", "")))

    # Normalizzazione espressioni shell frequenti generate da LLM (es. $(date +%Y-%m-%d))
    result = re.sub(r"\$\(date[^\)]*\)", today_str, result)

    # Chiavi testuali standard per estrazione fuzzy
    TEXT_KEYS = ("text", "result", "content", "body", "output", "response", "data", "summary")

    def _smart_lookup(val: Any, part: str) -> tuple[bool, Any]:
        if isinstance(val, dict):
            if part in val:
                return True, val[part]
            # Se cerca proprietà testuali (es. .text o .result o .content)
            if part in TEXT_KEYS:
                for alt in TEXT_KEYS:
                    if alt in val and val[alt] is not None:
                        return True, val[alt]
            # Se cerca .date
            if part == "date":
                if "date" in val and val["date"] is not None:
                    return True, str(val["date"])
                return True, today_str
        return False, None

    # Sostituzioni gerarchiche da context (inputs, config, steps, secrets)
    placeholders = re.findall(r"\{\{([a-zA-Z0-9_\.]+)\}\}", result)
    for p in placeholders:
        parts = p.split(".")
        val = context
        found = True
        for part in parts:
            found, next_val = _smart_lookup(val, part)
            if found:
                val = next_val
            else:
                break

        if found:
            # Se val è un dict, estrai il campo testuale principale se disponibile
            if isinstance(val, dict):
                extracted = False
                for tk in TEXT_KEYS:
                    if tk in val and isinstance(val[tk], str):
                        replacement = val[tk]
                        extracted = True
                        break
                if not extracted:
                    replacement = json.dumps(val, ensure_ascii=False, indent=2)
            elif isinstance(val, list):
                replacement = json.dumps(val, ensure_ascii=False, indent=2)
            else:
                replacement = str(val)

            result = result.replace(f"{{{{{p}}}}}", replacement)
        else:
            # Se il placeholder era relativo a steps (es. {{steps.step_1.output.text}}),
            # verifica se almeno il genitore esiste (es. output)
            if p.startswith("steps."):
                subparts = parts
                parent_val = context
                parent_found = True
                for sp in subparts[:-1]:
                    parent_found, next_v = _smart_lookup(parent_val, sp)
                    if parent_found:
                        parent_val = next_v
                    else:
                        break
                if parent_found and isinstance(parent_val, dict):
                    # Prova ad estrarre qualsiasi valore testuale dal genitore
                    extracted_fallback = False
                    for tk in TEXT_KEYS:
                        if tk in parent_val and parent_val[tk] is not None:
                            rep = str(parent_val[tk])
                            result = result.replace(f"{{{{{p}}}}}", rep)
                            extracted_fallback = True
                            break
                    if not extracted_fallback:
                        result = result.replace(f"{{{{{p}}}}}", json.dumps(parent_val, ensure_ascii=False))
                elif not parent_found:
                    logger.warning(f"Variabile template '{{{{{p}}}}}' non risolta nel contesto della run.")

    return result


def parse_xml_feed_to_text(xml_text: str, max_entries: int = 50) -> Optional[str]:
    """Se il testo è un feed XML (Atom / RSS), estrae gli item in formato testo compatto."""
    if not isinstance(xml_text, str) or not ("<feed" in xml_text or "<rss" in xml_text or "<xml" in xml_text):
        return None
    try:
        root = ET.fromstring(xml_text)
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]

        entries = root.findall(".//entry") or root.findall(".//item")
        if not entries:
            return None

        lines = [f"=== Feed con {len(entries)} elementi ==="]
        for idx, entry in enumerate(entries[:max_entries], 1):
            title_elem = entry.find("title")
            title = "".join(title_elem.itertext()).strip() if title_elem is not None else "Senza titolo"
            summary_elem = entry.find("summary")
            if summary_elem is None:
                summary_elem = entry.find("description")
            summary = "".join(summary_elem.itertext()).strip() if summary_elem is not None else ""

            link_elem = entry.find("link")
            link = ""
            if link_elem is not None:
                link = link_elem.attrib.get("href", "") or "".join(link_elem.itertext()).strip()

            published_elem = entry.find("published")
            if published_elem is None:
                published_elem = entry.find("pubDate")
            published = "".join(published_elem.itertext()).strip() if published_elem is not None else ""

            authors = []
            for a in entry.findall(".//author"):
                name_elem = a.find("name")
                if name_elem is not None and name_elem.text:
                    authors.append(name_elem.text.strip())
            authors_str = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "") if authors else ""

            entry_lines = [f"[{idx}] {title}"]
            if published:
                entry_lines.append(f"    Data: {published}")
            if authors_str:
                entry_lines.append(f"    Autori: {authors_str}")
            if link:
                entry_lines.append(f"    Link: {link}")
            if summary:
                clean_summary = " ".join(summary.split())
                entry_lines.append(f"    Abstract: {clean_summary}")
            lines.append("\n".join(entry_lines))

        return "\n\n".join(lines)
    except Exception as e:
        logger.debug(f"Parsing XML feed non riuscito: {e}")
        return None


def extract_step_content(step_ref: str, context: Dict[str, Any], max_chars: int = 30000) -> str:
    """Estrae il contenuto testuale o strutturato di uno step dal context delle run."""
    if not step_ref or not isinstance(step_ref, str):
        return ""

    clean_ref = step_ref.strip()
    if clean_ref.startswith("step:"):
        clean_ref = clean_ref[5:]
    elif clean_ref.startswith("steps."):
        clean_ref = clean_ref[6:]

    parts = clean_ref.split(".")
    target_step_id = parts[0]
    subfield = parts[1] if len(parts) > 1 else None

    step_info = context.get("steps", {}).get(target_step_id)
    if not step_info:
        logger.warning(f"Riferimento step '{step_ref}' non trovato nel context delle run.")
        return ""

    payload = step_info.get("output")
    if payload is None:
        return ""

    if subfield and isinstance(payload, dict) and subfield in payload:
        raw_val = payload[subfield]
    elif isinstance(payload, dict):
        if "text" in payload and isinstance(payload["text"], str):
            raw_val = payload["text"]
        elif "content" in payload and isinstance(payload["content"], str):
            raw_val = payload["content"]
        elif "data" in payload:
            raw_val = json.dumps(payload["data"], ensure_ascii=False, indent=2)
        else:
            raw_val = payload
    else:
        raw_val = payload

    if isinstance(raw_val, (dict, list)):
        raw_text = json.dumps(raw_val, ensure_ascii=False, indent=2)
    else:
        raw_text = str(raw_val)

    # Se il testo è un feed XML (Atom/RSS), compattalo
    parsed_feed = parse_xml_feed_to_text(raw_text)
    if parsed_feed:
        raw_text = parsed_feed

    if len(raw_text) > max_chars:
        raw_text = raw_text[:max_chars] + f"\n\n[... Troncato per limite di contesto ({len(raw_text)} caratteri totali) ...]"

    return raw_text


def resolve_parameters(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Applica render_template ai parametri (anche annidati) e risolve content_source / input_source."""
    resolved = {}
    for k, v in params.items():
        if isinstance(v, str):
            resolved[k] = render_template(v, context)
        elif isinstance(v, dict):
            resolved[k] = resolve_parameters(v, context)
        else:
            resolved[k] = v

    # Risoluzione automatica di content_source / input_source per step deterministici
    if "content_source" in resolved and resolved["content_source"]:
        cs = str(resolved["content_source"])
        if cs.startswith("step:") or cs.startswith("steps.") or cs in context.get("steps", {}):
            extracted = extract_step_content(cs, context)
            if extracted:
                resolved["content"] = extracted
                resolved["body"] = extracted

    if "input_source" in resolved and resolved["input_source"]:
        is_src = str(resolved["input_source"])
        if is_src.startswith("step:") or is_src.startswith("steps.") or is_src in context.get("steps", {}):
            extracted = extract_step_content(is_src, context)
            if extracted:
                resolved["input_data"] = extracted

    # Risoluzione alias percorsi (filename -> path)
    if "filename" in resolved and "path" not in resolved:
        resolved["path"] = resolved["filename"]

    return resolved
