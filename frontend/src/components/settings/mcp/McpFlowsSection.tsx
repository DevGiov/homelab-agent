import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Lock, RotateCcw, Save } from 'lucide-react';
import type { MCPTool } from '../../../api/mcp';
import { deleteMcpFlow, listMcpFlows, saveMcpFlow, type McpFlowSetting } from '../../../api/security';
import type { Notify } from '../../../hooks/useFeedback';
import { formatApiError } from '../../../utils/error';
import { LABEL_NAMES, LEVELS, serverScopes, type SensitivityLevel } from '../../../utils/sensitivity';

type Draft = Omit<McpFlowSetting, 'scope'>;

const STRICTEST: Draft = { result_label: 'private', result_untrusted: false, clearance: 'public' };

const selectClass = 'bg-bg/60 border border-border rounded-md px-1.5 py-0.5 text-xs text-fg focus:border-accent cursor-pointer';

/**
 * Classificazione dei server per la sensibilità dei dati: quanto sono riservati i loro risultati e quali dati possono
 * ricevere negli argomenti. Un server non classificato vale come il più stretto (risultati privati, argomenti solo
 * pubblici): la classificazione la sceglie chi lo aggiunge.
 */
export const McpFlowsSection: React.FC<{ tools: MCPTool[]; notify: Notify }> = ({ tools, notify }) => {
  const [saved, setSaved] = useState<Record<string, Draft>>({});
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  // Finché la classificazione non arriva, nessun server va segnato come non classificato
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await listMcpFlows();
      const map = Object.fromEntries(res.scopes.map(({ scope, ...rest }) => [scope, rest]));
      setSaved(map);
      setDrafts(map);
      setLoaded(true);
    } catch (err) {
      notify('error', `Classificazione dei server non caricata: ${formatApiError(err)}`);
    }
  }, [notify]);

  useEffect(() => {
    load();
  }, [load]);

  // Server del catalogo e server classificati che ora non rispondono
  const scopes = useMemo(() => [...new Set([...serverScopes(tools.map((tool) => tool.name)), ...Object.keys(saved).filter((s) => !s.includes('__'))])].sort(), [tools, saved]);

  const draftOf = (scope: string): Draft => drafts[scope] ?? saved[scope] ?? STRICTEST;
  const change = (scope: string, patch: Partial<Draft>) => setDrafts((d) => ({ ...d, [scope]: { ...draftOf(scope), ...patch } }));
  const dirty = (scope: string) => JSON.stringify(draftOf(scope)) !== JSON.stringify(saved[scope] ?? STRICTEST) || !saved[scope];

  const save = async (scope: string) => {
    try {
      await saveMcpFlow(scope, draftOf(scope));
      notify('success', `Server '${scope}' classificato.`);
      await load();
    } catch (err) {
      notify('error', formatApiError(err));
    }
  };

  const reset = async (scope: string) => {
    try {
      await deleteMcpFlow(scope);
      notify('success', `Server '${scope}' torna non classificato (il più stretto).`);
      setDrafts((d) => {
        const next = { ...d };
        delete next[scope];
        return next;
      });
      await load();
    } catch (err) {
      notify('error', formatApiError(err));
    }
  };

  const levelSelect = (scope: string, field: 'result_label' | 'clearance', title: string) => (
    <select
      value={draftOf(scope)[field]}
      onChange={(e) => change(scope, { [field]: e.target.value as SensitivityLevel })}
      className={selectClass}
      aria-label={`${title} di ${scope}`}
      title={title}
    >
      {LEVELS.map((l) => (
        <option key={l} value={l} className="bg-panel text-fg">
          {LABEL_NAMES[l]}
        </option>
      ))}
    </select>
  );

  return (
    <div className="bg-panel/70 border border-border rounded-xl p-3.5 space-y-2.5" data-testid="mcp-flows">
      <div className="flex items-center gap-2">
        <Lock size={14} className="text-amber-400" />
        <h3 className="text-xs font-semibold text-fg">Sensibilità dei dati per server</h3>
      </div>
      <p className="text-xs text-fg-muted leading-relaxed">
        <strong>Risultati</strong>: quanto sono riservati i dati che il server restituisce (l'output di comandi e log resta sempre
        privato). <strong>Può ricevere</strong>: l'etichetta più alta che gli argomenti possono avere; oltre, l'agente chiede
        conferma mostrando cosa invierebbe. Un server che inoltra le richieste a servizi esterni dovrebbe ricevere solo dati
        pubblici. Un server non classificato vale come il più stretto.
      </p>
      {scopes.length === 0 && <p className="text-xs text-fg-muted italic">Nessun server MCP nel catalogo.</p>}
      <div className="space-y-1.5">
        {scopes.map((scope) => (
          <div key={scope} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 p-2 rounded-lg border border-border bg-bg/40">
            <span className="font-mono text-xs text-fg min-w-[8rem]">{scope}</span>
            {loaded && !saved[scope] && <span className="text-xs text-amber-300">non classificato</span>}
            <label className="flex items-center gap-1 text-xs text-fg-muted">
              Risultati {levelSelect(scope, 'result_label', 'Etichetta dei risultati')}
            </label>
            <label className="flex items-center gap-1 text-xs text-fg-muted">
              Può ricevere {levelSelect(scope, 'clearance', 'Etichetta più alta degli argomenti')}
            </label>
            <label className="flex items-center gap-1 text-xs text-fg-muted cursor-pointer" title="I risultati contengono testo scritto da altri (web, cataloghi esterni)">
              <input
                type="checkbox"
                checked={draftOf(scope).result_untrusted}
                onChange={(e) => change(scope, { result_untrusted: e.target.checked })}
                className="accent-amber-500"
                aria-label={`Risultati non attendibili di ${scope}`}
              />
              non attendibili
            </label>
            <div className="flex items-center gap-1 ml-auto">
              <button
                onClick={() => save(scope)}
                disabled={!dirty(scope)}
                className="p-1 rounded-md text-accent hover:bg-accent/10 disabled:opacity-30 cursor-pointer disabled:cursor-default"
                title="Salva la classificazione"
              >
                <Save size={13} />
              </button>
              {saved[scope] && (
                <button onClick={() => reset(scope)} className="p-1 rounded-md text-fg-muted hover:text-fg cursor-pointer" title="Togli la classificazione (torna il più stretto)">
                  <RotateCcw size={13} />
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
