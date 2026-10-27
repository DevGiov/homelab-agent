# Stato del progetto — homelab-agent

Assessment del 2026-10-26 sul branch `dev` (commit `4e9f040`, allineato su CT 125).

> **Aggiornamento 2026-10-26**: Fase A (consolidamento) completata, baseline `v0.9.0` su `main`. Resta solo da osservare il criterio delle 24 ore senza errori nei log di CT 125. Prossima fase: B (refactor architetturale). La sintesi qui sotto descrive lo stato dell'assessment iniziale.

| Documento | Contenuto |
| :--- | :--- |
| [01-CURRENT_STATE.md](01-CURRENT_STATE.md) | Architettura, funzionalità, deploy e metriche della codebase |
| [02-ISSUES.md](02-ISSUES.md) | Problemi rilevati, con evidenze e severità |
| [03-FIX_PLAN.md](03-FIX_PLAN.md) | Piano di correzione passo-passo, con criteri di completamento |
| [04-ROADMAP.md](04-ROADMAP.md) | Roadmap per fasi: consolidamento, refactor, nuove funzionalità |

## Sintesi

Il prodotto è funzionalmente ricco e il deploy su CT 125 è sano (`/v1/health` → `ok`, container up). La qualità di base però è rimasta indietro rispetto alle feature:

- **Bug in produzione**: la retention delle automazioni va in errore a ogni ciclo (`bulk_delete_runs()` riceve un parametro che non esiste), quindi le run storiche non vengono mai pulite.
- **Test non affidabili**: la suite completa non termina; 7 file si bloccano (dipendenze da servizi live) e 5 test falliscono.
- **Nessuna CI attiva**: `.github/` non è versionato e il workflow non è mai stato eseguito. *(Risolto in A4: [ci.yml](../../.github/workflows/ci.yml) bloccante su ruff, pytest, oxlint e build.)*
- **Debito strutturale**: moduli monolitici (`graph.py` 1730 righe, `api.py` 1202), fallback legacy MCP, test e database nella radice del backend. *(In corso nella Fase B: `api.py` diviso in B1, `graph.py` in B2.)*

**Priorità**: prima il consolidamento (Fase A di [04-ROADMAP.md](04-ROADMAP.md)), poi il refactor a pacchetti, poi le nuove funzionalità.

## Come aggiornare questi documenti

- A ogni milestone chiusa, aggiornare lo stato in [02-ISSUES.md](02-ISSUES.md) e [04-ROADMAP.md](04-ROADMAP.md) e la data in cima a questo file.
- Il vecchio [ROADMAP.md](../../ROADMAP.md) nella radice è storico (fasi 0–9, fino ad agosto 2026); la roadmap attiva è qui.
