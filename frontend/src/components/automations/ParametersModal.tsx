import React, { useState, useEffect } from 'react';
import {
  Sliders,
  Play,
  Save,
  X,
  Plus,
  Trash2,
  Shield,
  Info,
  RefreshCw,
} from 'lucide-react';
import {
  type AutomationSummary,
  getAutomation,
  createOrUpdateAutomation,
  triggerAutomationRun,
} from '../../api';

interface ParametersModalProps {
  automation: AutomationSummary | null;
  isOpen: boolean;
  mode: 'edit' | 'run';
  onClose: () => void;
  onFeedback: (type: 'success' | 'error', text: string) => void;
  onSuccess: () => void;
}

export const ParametersModal: React.FC<ParametersModalProps> = ({
  automation,
  isOpen,
  mode,
  onClose,
  onFeedback,
  onSuccess,
}) => {
  const [paramsList, setParamsList] = useState<Array<{ key: string; value: string }>>([]);
  const [isDryRun, setIsDryRun] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [newKey, setNewKey] = useState<string>('');
  const [newValue, setNewValue] = useState<string>('');

  useEffect(() => {
    if (!isOpen || !automation) return;

    const loadAutomationDetail = async () => {
      setIsLoading(true);
      try {
        const full = await getAutomation(automation.id);
        const p = full.parameters || automation.parameters || {};
        const list = Object.entries(p).map(([k, v]) => ({
          key: k,
          value: typeof v === 'object' ? JSON.stringify(v) : String(v),
        }));
        setParamsList(list);
      } catch {
        // Fallback to summary parameters
        const p = automation.parameters || {};
        const list = Object.entries(p).map(([k, v]) => ({
          key: k,
          value: typeof v === 'object' ? JSON.stringify(v) : String(v),
        }));
        setParamsList(list);
      } finally {
        setIsLoading(false);
      }
    };

    loadAutomationDetail();
  }, [isOpen, automation]);

  if (!isOpen || !automation) return null;

  const handleAddParam = () => {
    if (!newKey.trim()) return;
    setParamsList((prev) => [...prev, { key: newKey.trim(), value: newValue.trim() }]);
    setNewKey('');
    setNewValue('');
  };

  const handleRemoveParam = (index: number) => {
    setParamsList((prev) => prev.filter((_, i) => i !== index));
  };

  const handleUpdateValue = (index: number, val: string) => {
    setParamsList((prev) => {
      const copy = [...prev];
      copy[index] = { ...copy[index], value: val };
      return copy;
    });
  };

  const buildParamsObject = (): Record<string, any> => {
    const obj: Record<string, any> = {};
    for (const item of paramsList) {
      if (!item.key.trim()) continue;
      // Tentativo di parsing JSON (numeri, boolean, array, oggetti)
      const val = item.value.trim();
      if (val === 'true') obj[item.key] = true;
      else if (val === 'false') obj[item.key] = false;
      else if (!isNaN(Number(val)) && val !== '') obj[item.key] = Number(val);
      else {
        try {
          if ((val.startsWith('{') && val.endsWith('}')) || (val.startsWith('[') && val.endsWith(']'))) {
            obj[item.key] = jsonParse(val);
          } else {
            obj[item.key] = val;
          }
        } catch {
          obj[item.key] = val;
        }
      }
    }
    return obj;
  };

  function jsonParse(str: string) {
    return JSON.parse(str);
  }

  const handleSaveDefaults = async () => {
    setIsSaving(true);
    try {
      const full = await getAutomation(automation.id);
      full.parameters = buildParamsObject();
      await createOrUpdateAutomation(full);
      onFeedback('success', `Parametri predefiniti per "${automation.name}" salvati con successo!`);
      onSuccess();
      onClose();
    } catch (err: any) {
      onFeedback('error', `Errore salvataggio: ${err?.response?.data?.detail || err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleExecute = async () => {
    setIsSaving(true);
    try {
      const payload = buildParamsObject();
      const res = await triggerAutomationRun(automation.id, isDryRun, false, payload);
      onFeedback(
        'success',
        `${isDryRun ? 'Dry-Run (anteprima)' : 'Esecuzione'} avviata con parametri per ${automation.id} (ID: ${res.run_id})`
      );
      onSuccess();
      onClose();
    } catch (err: any) {
      onFeedback('error', `Errore avvio run: ${err?.response?.data?.detail || err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-bg/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="w-full max-w-xl bg-panel border border-border rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="p-4 border-b border-border bg-panel-header/50 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
              <Sliders size={16} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold text-fg">
                  {mode === 'run' ? 'Esegui con Parametri' : 'Configura Parametri'}
                </h2>
                {isLoading && <RefreshCw size={12} className="animate-spin text-accent" />}
              </div>
              <p className="text-[11px] text-fg-muted font-mono">{automation.name} ({automation.id})</p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="p-5 overflow-y-auto space-y-4 text-xs">
          <div className="p-3 rounded-xl bg-bg/50 border border-border/60 flex items-start gap-2 text-[11px] text-fg-muted">
            <Info size={14} className="text-accent shrink-0 mt-0.5" />
            <span>
              {mode === 'run'
                ? 'I valori inseriti qui sovrascriveranno i parametri predefiniti esclusivamente per questa esecuzione manuale.'
                : 'Questi parametri fungono da valori predefiniti iniettati nei template {{inputs.chiave}} o {{config.chiave}} durante i trigger cron e manuali.'}
            </span>
          </div>

          {/* Parameters Table */}
          <div className="space-y-2">
            <label className="text-[11px] font-semibold text-fg block">
              Variabili & Parametri Workflow ({paramsList.length})
            </label>

            {paramsList.length === 0 ? (
              <div className="p-4 border border-dashed border-border rounded-xl text-center text-fg-muted text-[11px]">
                Nessun parametro configurato. Aggiungi variabili sotto (es. <code>email_recipient</code>, <code>max_items</code>, <code>category</code>).
              </div>
            ) : (
              <div className="space-y-2">
                {paramsList.map((item, idx) => (
                  <div key={idx} className="flex items-center gap-2 p-2 rounded-xl bg-bg border border-border/80">
                    <div className="w-1/3">
                      <span className="font-mono text-[11px] text-accent font-semibold block truncate" title={item.key}>
                        {item.key}
                      </span>
                    </div>
                    <div className="flex-1">
                      <input
                        type="text"
                        value={item.value}
                        onChange={(e) => handleUpdateValue(idx, e.target.value)}
                        className="w-full px-2 py-1 rounded-lg bg-panel border border-border text-fg text-xs font-mono focus:outline-none focus:border-accent"
                        placeholder="Valore..."
                      />
                    </div>
                    <button
                      onClick={() => handleRemoveParam(idx)}
                      className="p-1 text-fg-muted hover:text-rose-400 rounded-lg transition"
                      title="Rimuovi parametro"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Add parameter row */}
            <div className="pt-2 flex items-center gap-2">
              <input
                type="text"
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
                placeholder="Nuova chiave (es. max_items)"
                className="w-1/3 px-2.5 py-1.5 rounded-lg bg-bg border border-border text-fg text-xs font-mono focus:outline-none focus:border-accent"
              />
              <input
                type="text"
                value={newValue}
                onChange={(e) => setNewValue(e.target.value)}
                placeholder="Valore..."
                className="flex-1 px-2.5 py-1.5 rounded-lg bg-bg border border-border text-fg text-xs font-mono focus:outline-none focus:border-accent"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleAddParam();
                }}
              />
              <button
                type="button"
                onClick={handleAddParam}
                disabled={!newKey.trim()}
                className="px-3 py-1.5 bg-panel border border-border hover:border-accent/50 text-fg rounded-lg text-xs font-medium flex items-center gap-1 transition disabled:opacity-50"
              >
                <Plus size={13} /> Aggiungi
              </button>
            </div>
          </div>

          {/* Mode-specific Run Options */}
          {mode === 'run' && (
            <div className="p-3 rounded-xl bg-panel border border-border/80 flex items-center justify-between mt-4">
              <div className="flex items-center gap-2">
                <Shield size={16} className="text-purple-400" />
                <div>
                  <span className="text-xs font-medium text-fg block">Esegui in modalità Dry-Run</span>
                  <span className="text-[11px] text-fg-muted">Simula i passaggi senza apportare modifiche o side effect</span>
                </div>
              </div>

              <input
                type="checkbox"
                checked={isDryRun}
                onChange={(e) => setIsDryRun(e.target.checked)}
                className="rounded border-border text-purple-500 focus:ring-0 cursor-pointer w-4 h-4"
              />
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-border bg-panel-header/30 flex items-center justify-between">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-xs text-fg-muted hover:text-fg transition"
          >
            Annulla
          </button>

          <div className="flex items-center gap-2">
            {mode === 'edit' ? (
              <button
                onClick={handleSaveDefaults}
                disabled={isSaving}
                className="px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-medium flex items-center gap-1.5 shadow-sm transition disabled:opacity-50"
              >
                <Save size={13} /> {isSaving ? 'Salvataggio...' : 'Salva Parametri Predefiniti'}
              </button>
            ) : (
              <button
                onClick={handleExecute}
                disabled={isSaving}
                className="px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-medium flex items-center gap-1.5 shadow-sm transition disabled:opacity-50"
              >
                <Play size={13} /> {isSaving ? 'Avvio in corso...' : isDryRun ? 'Avvia Dry-Run' : 'Avvia Esecuzione'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
