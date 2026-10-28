import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Edit2, Loader2, PlugZap, Server, Trash2 } from 'lucide-react';
import type { MCPServer, MCPTool, ToolRisk } from '../../../api/mcp';
import { Toggle } from '../../Toggle';

const RISKS: Array<[ToolRisk, string]> = [
  ['auto', 'Automatico'],
  ['view', 'Lettura'],
  ['confirm', 'Conferma'],
  ['blocked', 'Bloccato'],
];

interface ServerCardProps {
  server: MCPServer;
  tools: MCPTool[];
  onToggle: (enabled: boolean) => void;
  onEdit: () => void;
  onDelete: () => void;
  onTest: () => Promise<void>;
  onToolChange: (tool: MCPTool, change: { enabled: boolean; risk: ToolRisk }) => void;
}

/** Nome del tool senza il prefisso del server, che la card mostra già. */
const shortName = (tool: MCPTool) => (tool.name.startsWith(`${tool.server}__`) ? tool.name.slice(tool.server.length + 2) : tool.name);

function statusBadge(server: MCPServer) {
  if (!server.enabled) return { label: 'Disattivato', className: 'bg-panel-header text-fg-muted border-border' };
  if (!server.status) return { label: 'Mai contattato', className: 'bg-panel-header text-fg-muted border-border' };
  if (server.status.ok) return { label: `${server.status.tool_count} tool`, className: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' };
  return { label: 'Non raggiungibile', className: 'bg-rose-500/15 text-rose-300 border-rose-500/30' };
}

export const ServerCard: React.FC<ServerCardProps> = ({ server, tools, onToggle, onEdit, onDelete, onTest, onToolChange }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const badge = statusBadge(server);
  const disabledCount = tools.filter((t) => !t.enabled).length;

  const test = async () => {
    setIsTesting(true);
    await onTest();
    setIsTesting(false);
  };

  return (
    <div className="rounded-xl border border-border bg-panel/60">
      <div className="p-3 flex items-start justify-between gap-2">
        <div className="flex items-start gap-2.5 min-w-0">
          <div className="p-1.5 rounded-lg bg-accent/10 border border-accent/20 text-accent shrink-0">
            <Server size={14} />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-xs font-semibold text-fg">{server.name}</span>
              <span className="font-mono text-[10px] text-fg-muted">{server.id}</span>
              {server.builtin && (
                <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-accent/10 text-accent border border-accent/30">.env</span>
              )}
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${badge.className}`}>{badge.label}</span>
            </div>
            <p className="font-mono text-[10px] text-fg-muted truncate">{server.url}</p>
            {server.enabled && server.status?.error && <p className="text-[10px] text-rose-400 mt-0.5 line-clamp-2">{server.status.error}</p>}
          </div>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <button onClick={test} disabled={isTesting} className="p-1.5 rounded-lg text-fg-muted hover:text-accent hover:bg-panel-hover cursor-pointer" title="Prova connessione">
            {isTesting ? <Loader2 size={13} className="animate-spin" /> : <PlugZap size={13} />}
          </button>
          {!server.builtin && (
            <>
              <button onClick={onEdit} className="p-1.5 rounded-lg text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer" title="Modifica server">
                <Edit2 size={13} />
              </button>
              <button onClick={onDelete} className="p-1.5 rounded-lg text-fg-muted hover:text-rose-400 hover:bg-panel-hover cursor-pointer" title="Elimina server">
                <Trash2 size={13} />
              </button>
              <Toggle checked={server.enabled} onChange={onToggle} size="sm" activeClass="peer-checked:bg-emerald-500" title={server.enabled ? 'Disattiva server' : 'Attiva server'} />
            </>
          )}
        </div>
      </div>

      {tools.length > 0 && (
        <>
          <button
            onClick={() => setIsOpen(!isOpen)}
            className="w-full px-3 py-1.5 border-t border-border/60 flex items-center justify-between text-[11px] text-fg-muted hover:text-fg cursor-pointer"
          >
            <span className="flex items-center gap-1">
              {isOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              Tool ({tools.length}){disabledCount > 0 && ` · ${disabledCount} disattivati`}
            </span>
          </button>
          {isOpen && (
            <div className="border-t border-border/60 divide-y divide-border/40 max-h-72 overflow-y-auto custom-scrollbar">
              {tools.map((tool) => (
                <div key={tool.name} className={`px-3 py-1.5 flex items-center gap-2 ${tool.enabled ? '' : 'opacity-50'}`}>
                  <Toggle checked={tool.enabled} onChange={(enabled) => onToolChange(tool, { enabled, risk: tool.risk })} size="sm" title={tool.enabled ? 'Disattiva tool' : 'Attiva tool'} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-[11px] text-fg truncate">{shortName(tool)}</span>
                      <span
                        className={`text-[9px] px-1 rounded border ${
                          tool.access === 'view' ? 'text-emerald-300 border-emerald-500/30' : 'text-amber-300 border-amber-500/30'
                        }`}
                        title={tool.access === 'view' ? 'Eseguito senza conferma in modalità Normal' : 'Soggetto alle regole di approvazione'}
                      >
                        {tool.access === 'view' ? 'lettura' : 'esecuzione'}
                      </span>
                    </div>
                    <p className="text-[10px] text-fg-muted truncate" title={tool.description}>
                      {tool.description}
                    </p>
                  </div>
                  <select
                    value={tool.risk}
                    onChange={(e) => onToolChange(tool, { enabled: tool.enabled, risk: e.target.value as ToolRisk })}
                    className={`bg-input-bg border border-input-border rounded-md px-1.5 py-0.5 text-[10px] focus:outline-none focus:border-accent ${
                      tool.risk === 'blocked' ? 'text-rose-400' : 'text-fg'
                    }`}
                    title="Rischio: Automatico usa la classificazione per nome"
                  >
                    {RISKS.map(([value, label]) => (
                      <option key={value} value={value} className="bg-panel text-fg">
                        {label}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
};
