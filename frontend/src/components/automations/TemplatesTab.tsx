import React from 'react';
import { Mail, Plus, Shield } from 'lucide-react';
import { createOrUpdateAutomation } from '../../api/automations';
import type { Notify } from '../../hooks/useFeedback';
import { formatApiError } from '../../utils/error';

interface TemplatesTabProps {
  templates: any[];
  notify: Notify;
  onInstalled: () => void;
}

export const TemplatesTab: React.FC<TemplatesTabProps> = ({ templates, notify, onInstalled }) => {
  const install = async (template: any) => {
    try {
      await createOrUpdateAutomation(template);
      notify('success', `Template "${template.name}" installato e attivato con successo!`);
      onInstalled();
    } catch (err) {
      notify('error', `Errore installazione template: ${formatApiError(err)}`);
    }
  };

  return (
    <div className="space-y-4">
      <h2 className="text-xs font-semibold text-fg-muted uppercase tracking-wider">Template Pronti all'Uso (Homelab Best Practices)</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {templates.map((tpl) => (
          <div
            key={tpl.id}
            className="p-5 rounded-2xl bg-panel border border-accent/40 shadow-md flex flex-col justify-between space-y-4 relative overflow-hidden"
          >
            <div className="absolute top-0 right-0 bg-accent/20 px-3 py-1 text-[10px] font-bold text-accent rounded-bl-xl border-l border-b border-accent/30">
              MVP READY
            </div>

            <div>
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-accent/20 text-accent flex items-center justify-center">
                  <Mail size={18} />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-fg">{tpl.name}</h3>
                  <span className="text-[11px] font-mono text-fg-muted">{tpl.id}</span>
                </div>
              </div>

              <p className="text-xs text-fg-muted mt-3">{tpl.description}</p>

              <div className="mt-4 p-3 rounded-xl bg-bg/50 border border-border/60 space-y-2 text-xs">
                <span className="font-semibold text-fg block text-[11px]">Workflow Steps:</span>
                <ol className="list-decimal list-inside space-y-1 text-fg-muted text-[11px]">
                  {tpl.workflow?.steps?.map((st: any) => (
                    <li key={st.step_id}>
                      <span className="font-medium text-fg">{st.name}</span> <span className="text-[10px] font-mono">({st.type})</span>
                    </li>
                  ))}
                </ol>
              </div>

              <div className="mt-3 p-2.5 rounded-lg bg-emerald-950/30 border border-emerald-800/40 text-[11px] text-emerald-300 flex items-center gap-2">
                <Shield size={14} className="shrink-0 text-emerald-400" />
                <span>Sicurezza: Nessun invio automatico. Genera solo bozze e report Markdown.</span>
              </div>
            </div>

            <button
              onClick={() => install(tpl)}
              className="w-full py-2.5 px-4 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-2 shadow-md transition cursor-pointer active:scale-[0.99]"
            >
              <Plus size={16} /> Installa ed Attiva Automazione
            </button>
          </div>
        ))}
      </div>
    </div>
  );
};
