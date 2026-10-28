import React, { useCallback, useEffect, useState } from 'react';
import { Loader2, Plus, RefreshCw } from 'lucide-react';
import {
  createMcpServer,
  deleteMcpServer,
  listMcpServers,
  listMcpTools,
  reloadMcpServers,
  testMcpServer,
  updateMcpServer,
  updateMcpTool,
  type MCPServer,
  type MCPTool,
} from '../../../api/mcp';
import { useFeedback } from '../../../hooks/useFeedback';
import { formatApiError } from '../../../utils/error';
import { ServerCard } from './ServerCard';
import { ServerForm } from './ServerForm';

/** Server MCP collegati all'agente e impostazioni dei loro tool; le modifiche valgono subito, senza riavvio. */
export const McpTab: React.FC = () => {
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [form, setForm] = useState<{ server?: MCPServer } | null>(null);
  const { feedback, notify } = useFeedback();

  const load = useCallback(
    async (refresh = false) => {
      setIsLoading(true);
      try {
        if (refresh) await reloadMcpServers();
        const [serverList, toolList] = await Promise.all([listMcpServers(), listMcpTools()]);
        setServers(serverList);
        setTools(toolList);
      } catch (err) {
        notify('error', `Server MCP non caricati: ${formatApiError(err)}`);
      } finally {
        setIsLoading(false);
      }
    },
    [notify]
  );

  useEffect(() => {
    load();
  }, [load]);

  const attempt = async (action: () => Promise<unknown>, success: string) => {
    try {
      await action();
      notify('success', success);
      await load();
    } catch (err) {
      notify('error', formatApiError(err));
    }
  };

  const changeTool = async (tool: MCPTool, change: { enabled: boolean; risk: MCPTool['risk'] }) => {
    try {
      const updated = await updateMcpTool(tool.name, change);
      setTools((prev) => prev.map((t) => (t.name === tool.name ? { ...t, ...updated } : t)));
    } catch (err) {
      notify('error', formatApiError(err));
    }
  };

  const test = async (server: MCPServer) => {
    try {
      const res = await testMcpServer(server.id);
      if (res.ok) notify('success', `${server.name}: connesso in ${res.latency_ms} ms, ${res.tool_count} tool.`);
      else notify('error', `${server.name}: ${res.error}`);
    } catch (err) {
      notify('error', formatApiError(err));
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[11px] text-fg-muted leading-relaxed">
          Server MCP collegati all'agente. I tool dei server aggiunti qui prendono il prefisso <code>id__</code>. Rischio{' '}
          <strong>Lettura</strong> esegue senza conferma, <strong>Conferma</strong> chiede sempre approvazione, <strong>Bloccato</strong> non
          esegue mai; <strong>Automatico</strong> usa la classificazione per nome.
        </p>
        <button
          onClick={() => load(true)}
          disabled={isLoading}
          className="p-1.5 rounded-lg border border-border text-fg-muted hover:text-fg hover:bg-panel-hover shrink-0 cursor-pointer"
          title="Ricarica i cataloghi di tutti i server"
        >
          <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      {feedback && (
        <div
          className={`p-2 rounded-lg text-[11px] border ${
            feedback.type === 'success' ? 'bg-emerald-950/40 border-emerald-800/60 text-emerald-300' : 'bg-rose-950/40 border-rose-800/60 text-rose-300'
          }`}
        >
          {feedback.text}
        </div>
      )}

      {form ? (
        <ServerForm
          server={form.server}
          onCancel={() => setForm(null)}
          onSubmit={async ({ id, ...input }) => {
            if (form.server) await updateMcpServer(id, input);
            else await createMcpServer({ id, ...input });
            setForm(null);
            notify('success', form.server ? `Server '${input.name}' aggiornato.` : `Server '${input.name}' aggiunto.`);
            await load();
          }}
        />
      ) : (
        <button
          onClick={() => setForm({})}
          className="w-full py-1.5 rounded-xl border border-dashed border-accent/40 text-accent hover:bg-accent/10 text-xs flex items-center justify-center gap-1.5 cursor-pointer"
        >
          <Plus size={13} /> Aggiungi server MCP
        </button>
      )}

      {isLoading && servers.length === 0 ? (
        <div className="flex items-center justify-center gap-2 py-6 text-xs text-fg-muted">
          <Loader2 size={14} className="animate-spin text-accent" /> Interrogazione dei server…
        </div>
      ) : (
        servers.map((server) => (
          <ServerCard
            key={server.id}
            server={server}
            tools={tools.filter((t) => t.server === server.id)}
            onToggle={(enabled) =>
              attempt(
                () => updateMcpServer(server.id, { name: server.name, url: server.url, enabled }),
                `Server '${server.name}' ${enabled ? 'attivato' : 'disattivato'}.`
              )
            }
            onEdit={() => setForm({ server })}
            onDelete={() => {
              if (confirm(`Eliminare il server '${server.name}'? I suoi tool spariranno dal catalogo dell'agente.`)) {
                attempt(() => deleteMcpServer(server.id), `Server '${server.name}' eliminato.`);
              }
            }}
            onTest={() => test(server)}
            onToolChange={changeTool}
          />
        ))
      )}
    </div>
  );
};
