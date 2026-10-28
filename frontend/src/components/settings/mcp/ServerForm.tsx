import React, { useState } from 'react';
import { CheckCircle2, Loader2, PlugZap, XCircle } from 'lucide-react';
import { testMcpConnection, testMcpServer, type MCPServer, type MCPServerInput, type MCPTestResult } from '../../../api/mcp';
import { formatApiError } from '../../../utils/error';

const inputClass =
  'w-full bg-input-bg border border-input-border rounded-lg px-2.5 py-1.5 text-xs text-fg placeholder:text-fg-muted/50 focus:outline-none focus:border-accent';
const labelClass = 'block text-[11px] font-medium text-fg-muted mb-1';

interface ServerFormProps {
  /** Server da modificare; assente per un nuovo server. */
  server?: MCPServer;
  onSubmit: (input: MCPServerInput & { id: string }) => Promise<void>;
  onCancel: () => void;
}

/** Dati di un server MCP con prova di connessione prima del salvataggio. */
export const ServerForm: React.FC<ServerFormProps> = ({ server, onSubmit, onCancel }) => {
  const [id, setId] = useState(server?.id ?? '');
  const [name, setName] = useState(server?.name ?? '');
  const [url, setUrl] = useState(server?.url ?? '');
  const [token, setToken] = useState('');
  const [removeToken, setRemoveToken] = useState(false);
  const [test, setTest] = useState<MCPTestResult | null>(null);
  const [isTesting, setIsTesting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isEdit = Boolean(server);

  const runTest = async () => {
    setIsTesting(true);
    setTest(null);
    try {
      // Server salvato con URL e token invariati: la prova usa il token salvato, che la UI non conosce
      const useSaved = server && server.url === url && !token && !removeToken;
      setTest(useSaved ? await testMcpServer(server.id) : await testMcpConnection(url, token));
    } catch (err) {
      setTest({ ok: false, error: formatApiError(err), latency_ms: 0 });
    } finally {
      setIsTesting(false);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setError(null);
    try {
      // In modifica: token vuoto = invariato, salvo richiesta esplicita di rimuoverlo
      const tokenField = isEdit ? (removeToken ? '' : token || undefined) : token;
      await onSubmit({ id, name, url, token: tokenField, enabled: server?.enabled ?? true });
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="p-3 rounded-xl border border-accent/40 bg-accent/5 space-y-2.5">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className={labelClass}>Id (prefisso dei tool)</label>
          <input
            value={id}
            onChange={(e) => setId(e.target.value.toLowerCase())}
            disabled={isEdit}
            required
            pattern="[a-z0-9][a-z0-9\-]{1,30}"
            placeholder="es. creative-suite"
            className={`${inputClass} font-mono disabled:opacity-60`}
          />
        </div>
        <div>
          <label className={labelClass}>Nome</label>
          <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="es. Creative Suite" className={inputClass} />
        </div>
      </div>
      <div>
        <label className={labelClass}>URL (Streamable HTTP)</label>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          required
          placeholder="http://192.168.1.189:8000/mcp"
          className={`${inputClass} font-mono`}
        />
      </div>
      <div>
        <label className={labelClass}>Token Bearer (opzionale, cifrato a riposo)</label>
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          disabled={removeToken}
          placeholder={isEdit && server?.has_token ? 'Lascia vuoto per mantenere quello salvato' : 'Nessun token'}
          className={`${inputClass} font-mono disabled:opacity-60`}
        />
        {isEdit && server?.has_token && (
          <label className="flex items-center gap-1.5 mt-1 text-[11px] text-fg-muted cursor-pointer">
            <input type="checkbox" checked={removeToken} onChange={(e) => setRemoveToken(e.target.checked)} />
            Rimuovi il token salvato
          </label>
        )}
      </div>

      {test && (
        <div
          className={`p-2 rounded-lg text-[11px] flex items-start gap-1.5 border ${
            test.ok ? 'bg-emerald-950/40 border-emerald-800/60 text-emerald-300' : 'bg-rose-950/40 border-rose-800/60 text-rose-300'
          }`}
        >
          {test.ok ? <CheckCircle2 size={13} className="shrink-0 mt-px" /> : <XCircle size={13} className="shrink-0 mt-px" />}
          <span className="min-w-0 break-words">
            {test.ok ? `Connesso in ${test.latency_ms} ms: ${test.tool_count} tool (${test.tools?.slice(0, 6).join(', ')}${(test.tool_count ?? 0) > 6 ? ', …' : ''})` : test.error}
          </span>
        </div>
      )}
      {error && <div className="p-2 rounded-lg text-[11px] bg-rose-950/40 border border-rose-800/60 text-rose-300">{error}</div>}

      <div className="flex items-center justify-between gap-2 pt-1">
        <button
          type="button"
          onClick={runTest}
          disabled={isTesting || !url}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border bg-panel hover:bg-panel-hover text-xs text-fg disabled:opacity-50 cursor-pointer"
        >
          {isTesting ? <Loader2 size={12} className="animate-spin" /> : <PlugZap size={12} />}
          Prova connessione
        </button>
        <div className="flex items-center gap-2">
          <button type="button" onClick={onCancel} className="px-2.5 py-1.5 rounded-lg text-xs text-fg-muted hover:text-fg cursor-pointer">
            Annulla
          </button>
          <button
            type="submit"
            disabled={isSaving}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-white text-xs font-semibold disabled:opacity-50 cursor-pointer"
          >
            {isSaving && <Loader2 size={12} className="animate-spin" />}
            {isEdit ? 'Salva' : 'Aggiungi server'}
          </button>
        </div>
      </div>
    </form>
  );
};
