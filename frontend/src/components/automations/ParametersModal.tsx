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
  Key,
  Code2,
} from 'lucide-react';
import {
  type AutomationSummary,
  getAutomation,
  createOrUpdateAutomation,
  triggerAutomationRun,
  introspectAutomationParameters,
  type IntrospectionResult,
  type IntrospectedParameter,
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
  const [detectedValues, setDetectedValues] = useState<Record<string, any>>({});
  const [introspection, setIntrospection] = useState<IntrospectionResult | null>(null);
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
        const [full, intro] = await Promise.all([
          getAutomation(automation.id).catch(() => ({ parameters: automation.parameters || {} })),
          introspectAutomationParameters(automation.id).catch(() => null),
        ]);

        const existingParams = full.parameters || automation.parameters || {};
        setIntrospection(intro);

        // Populate detected parameters values
        const detectedMap: Record<string, any> = {};
        const detectedKeys = new Set<string>();

        if (intro) {
          const allDetected = [...(intro.parameters || []), ...(intro.variables || [])];
          for (const param of allDetected) {
            detectedKeys.add(param.name);
            if (param.name in existingParams) {
              detectedMap[param.name] = existingParams[param.name];
            } else if (param.default !== undefined && param.default !== null) {
              detectedMap[param.name] = param.default;
            } else if (param.type === 'boolean') {
              detectedMap[param.name] = false;
            } else {
              detectedMap[param.name] = '';
            }
          }
        }
        setDetectedValues(detectedMap);

        // Put any additional parameters not in detected into custom paramsList
        const customList: Array<{ key: string; value: string }> = [];
        for (const [k, v] of Object.entries(existingParams)) {
          if (!detectedKeys.has(k)) {
            customList.push({
              key: k,
              value: typeof v === 'object' ? JSON.stringify(v) : String(v),
            });
          }
        }
        setParamsList(customList);
      } catch (err: any) {
        console.error('Error loading automation parameters:', err);
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

  const handleUpdateCustomValue = (index: number, val: string) => {
    setParamsList((prev) => {
      const copy = [...prev];
      copy[index] = { ...copy[index], value: val };
      return copy;
    });
  };

  const handleUpdateDetectedValue = (name: string, val: any) => {
    setDetectedValues((prev) => ({
      ...prev,
      [name]: val,
    }));
  };

  const buildParamsObject = (): Record<string, any> => {
    const obj: Record<string, any> = {};

    // 1. Detected values
    for (const [key, val] of Object.entries(detectedValues)) {
      if (val === undefined || val === null) continue;
      if (typeof val === 'string' && val.trim() === '') continue;
      obj[key] = val;
    }

    // 2. Custom values
    for (const item of paramsList) {
      if (!item.key.trim()) continue;
      const val = item.value.trim();
      if (val === 'true') obj[item.key] = true;
      else if (val === 'false') obj[item.key] = false;
      else if (!isNaN(Number(val)) && val !== '') obj[item.key] = Number(val);
      else {
        try {
          if ((val.startsWith('{') && val.endsWith('}')) || (val.startsWith('[') && val.endsWith(']'))) {
            obj[item.key] = JSON.parse(val);
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

  const detectedParamsList: IntrospectedParameter[] = [
    ...(introspection?.parameters || []),
    ...(introspection?.variables || []),
  ];

  const getTypeBadgeClass = (type: string) => {
    switch (type.toLowerCase()) {
      case 'number':
        return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30';
      case 'boolean':
        return 'bg-amber-500/15 text-amber-300 border-amber-500/30';
      case 'secret':
        return 'bg-purple-500/15 text-purple-300 border-purple-500/30';
      default:
        return 'bg-sky-500/15 text-sky-300 border-sky-500/30';
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
        <div className="p-5 overflow-y-auto space-y-5 text-xs">
          <div className="p-3 rounded-xl bg-bg/50 border border-border/60 flex items-start gap-2 text-[11px] text-fg-muted">
            <Info size={14} className="text-accent shrink-0 mt-0.5" />
            <span>
              {mode === 'run'
                ? 'I valori inseriti qui sovrascriveranno i parametri predefiniti esclusivamente per questa esecuzione manuale.'
                : 'Questi parametri fungono da valori predefiniti iniettati nei template {{inputs.chiave}} o {{config.chiave}} durante i trigger cron e manuali.'}
            </span>
          </div>

          {/* Section 1: Detected Parameters from Introspection */}
          {detectedParamsList.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-[11px] font-semibold text-fg flex items-center gap-1.5">
                  <Code2 size={13} className="text-accent" />
                  Parametri Rilevati dal Workflow ({detectedParamsList.length})
                </label>
                <span className="text-[10px] text-fg-muted">Rilevamento AST automatico</span>
              </div>

              <div className="space-y-2">
                {detectedParamsList.map((param) => {
                  const val = detectedValues[param.name] ?? '';
                  const isBool = param.type === 'boolean';
                  const isNum = param.type === 'number';

                  return (
                    <div
                      key={param.name}
                      className="p-3 rounded-xl bg-bg border border-border/80 space-y-1.5 hover:border-accent/30 transition"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs text-accent font-semibold">
                            {param.name}
                          </span>
                          <span
                            className={`px-1.5 py-0.2 rounded text-[10px] font-mono border ${getTypeBadgeClass(
                              param.type
                            )}`}
                          >
                            {param.type}
                          </span>
                        </div>
                        {param.default !== undefined && param.default !== null && (
                          <span className="text-[10px] text-fg-muted font-mono">
                            default: {String(param.default)}
                          </span>
                        )}
                      </div>

                      {param.description && (
                        <p className="text-[11px] text-fg-muted">{param.description}</p>
                      )}

                      <div>
                        {isBool ? (
                          <label className="flex items-center gap-2 cursor-pointer pt-1">
                            <input
                              type="checkbox"
                              checked={Boolean(val)}
                              onChange={(e) =>
                                handleUpdateDetectedValue(param.name, e.target.checked)
                              }
                              className="rounded border-border text-accent focus:ring-0 w-4 h-4 cursor-pointer"
                            />
                            <span className="text-xs text-fg">
                              {Boolean(val) ? 'Attivato (true)' : 'Disattivato (false)'}
                            </span>
                          </label>
                        ) : (
                          <input
                            type={isNum ? 'number' : 'text'}
                            value={val}
                            onChange={(e) =>
                              handleUpdateDetectedValue(
                                param.name,
                                isNum ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value
                              )
                            }
                            placeholder={param.default !== undefined ? String(param.default) : 'Inserisci valore...'}
                            className="w-full px-2.5 py-1.5 rounded-lg bg-panel border border-border text-fg text-xs font-mono focus:outline-none focus:border-accent"
                          />
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Section 2: Detected Secrets */}
          {introspection && introspection.secrets && introspection.secrets.length > 0 && (
            <div className="p-3 rounded-xl bg-panel border border-purple-500/30 space-y-2">
              <div className="flex items-center gap-1.5 text-purple-300 font-semibold text-[11px]">
                <Key size={13} className="text-purple-400" />
                <span>Credenziali & Segreti Rilevati ({introspection.secrets.length})</span>
              </div>
              <p className="text-[11px] text-fg-muted">
                Questo workflow referenzia le seguenti chiavi segrete risolte tramite il Tier 1/2 delle Integrazioni:
              </p>
              <div className="flex flex-wrap gap-1.5 pt-1">
                {introspection.secrets.map((sec) => (
                  <span
                    key={sec.name}
                    className="px-2 py-0.5 rounded-md bg-purple-950/40 border border-purple-800/50 text-[11px] font-mono text-purple-300 flex items-center gap-1"
                    title={sec.description || sec.service}
                  >
                    <span>{sec.name}</span>
                    {sec.service && (
                      <span className="text-[9px] text-purple-400/70">({sec.service})</span>
                    )}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Section 3: Custom / Additional Parameters */}
          <div className="space-y-2">
            <label className="text-[11px] font-semibold text-fg block">
              {detectedParamsList.length > 0 ? 'Parametri Aggiuntivi (Custom)' : 'Parametri Workflow'} ({paramsList.length})
            </label>

            {paramsList.length === 0 && detectedParamsList.length === 0 ? (
              <div className="p-4 border border-dashed border-border rounded-xl text-center text-fg-muted text-[11px]">
                Nessun parametro configurato. Aggiungi variabili sotto (es. <code>email_recipient</code>, <code>max_items</code>).
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
                        onChange={(e) => handleUpdateCustomValue(idx, e.target.value)}
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
                placeholder="Nuova chiave (es. query)"
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
