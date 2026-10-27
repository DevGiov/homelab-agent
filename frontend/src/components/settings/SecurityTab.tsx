import React, { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Loader2, Lock, RefreshCw, Shield, ShieldAlert, ShieldCheck, Trash2, Zap, type LucideIcon } from 'lucide-react';
import {
  listGrantedPermissions,
  revokePermission,
  revokeThreadPermissions,
  type PermissionsListResponse,
} from '../../api/approvals';
import type { SecurityMode } from '../../api/chat';
import { useSecurityMode } from '../../hooks/useSecurityMode';

const MODES: Array<{
  mode: SecurityMode;
  label: string;
  icon: LucideIcon;
  tagline: string;
  description: React.ReactNode;
  color: string;
  selected: string;
  idle: string;
  dot: string;
}> = [
  {
    mode: 'safest',
    label: 'Safest',
    icon: Shield,
    tagline: 'Massima Sicurezza',
    description: (
      <>
        Qualunque tool esterno (inclusi VIEW come <code>get_container_status</code>) richiede conferma esplicita. Web search e
        memoria rimangono libere.
      </>
    ),
    color: 'text-emerald-400',
    selected: 'bg-emerald-950/40 border-emerald-500/60 ring-1 ring-emerald-500/40',
    idle: 'hover:border-emerald-500/30',
    dot: 'bg-emerald-400',
  },
  {
    mode: 'normal',
    label: 'Normal',
    icon: ShieldCheck,
    tagline: 'Bilanciata (Default)',
    description: (
      <>
        I tool <strong>VIEW</strong> (lettura) sono automatici. Tool di scrittura e comandi shell richiedono conferma (con allow-list
        comandi sicuri).
      </>
    ),
    color: 'text-accent',
    selected: 'bg-accent/15 border-accent ring-1 ring-accent/40',
    idle: 'hover:border-accent/30',
    dot: 'bg-accent',
  },
  {
    mode: 'dangerous',
    label: 'Dangerous',
    icon: Zap,
    tagline: 'Autonoma (No Prompt)',
    description: (
      <>
        Esecuzione autonoma senza prompt UI. La salvaguardia deterministica Tier 1 (<code>rm -rf /</code>) rimane comunque{' '}
        <strong>attiva e inviolabile</strong>.
      </>
    ),
    color: 'text-rose-400',
    selected: 'bg-rose-950/40 border-rose-500/60 ring-1 ring-rose-500/40',
    idle: 'hover:border-rose-500/30',
    dot: 'bg-rose-400',
  },
];

const BLOCKED_COMMANDS: React.ReactNode[] = [
  <>Wipe ricorsivo root/sistema (<code>rm -rf /</code>, <code>rm -rf /etc</code>, <code>~</code>, ecc.)</>,
  <>Formattazione dischi & firme filesystem (<code>mkfs</code>, <code>wipefs</code>)</>,
  <>Scrittura grezza su blocchi disco (<code>dd of=/dev/sd*</code>, <code>&gt; /dev/nvme*</code>)</>,
  <>Fork bomb, DoS di sistema e manomissione credenziali (<code>/etc/shadow</code>)</>,
  <>Download ed esecuzione arbitraria pipe-to-shell (<code>curl ... | sh</code>, <code>base64 -d | sh</code>)</>,
];

const revokeButton = 'p-1.5 text-rose-400 hover:text-rose-200 hover:bg-rose-950/40 rounded-lg transition cursor-pointer';

/** Modalità di sicurezza (condivisa con la toolbar della chat), guardrail Tier 1 e permessi Tier 2 accordati. */
export const SecurityTab: React.FC = () => {
  const [securityMode, setSecurityMode] = useSecurityMode();
  const [permissions, setPermissions] = useState<PermissionsListResponse>({ always: [], session: {} });
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPermissions(await listGrantedPermissions());
    } catch (err) {
      console.warn('Errore caricamento permessi:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const flash = (text: string) => {
    setMessage(text);
    setTimeout(() => setMessage(null), 3000);
  };

  const revoke = async (action: () => Promise<void>, success: string) => {
    try {
      await action();
      flash(success);
      await load();
    } catch (err) {
      console.error('Errore revoca permessi:', err);
    }
  };

  const selectMode = (mode: SecurityMode) => {
    setSecurityMode(mode);
    flash(`Modalità di sicurezza aggiornata a: ${mode.toUpperCase()}`);
  };

  const sessions = Object.entries(permissions.session);

  return (
    <div className="space-y-4">
      {message && (
        <div className="flex items-center gap-2 bg-emerald-950/70 border border-emerald-800/80 rounded-xl p-2.5 text-xs text-emerald-200">
          <CheckCircle2 size={14} className="text-emerald-400 shrink-0" />
          <span>{message}</span>
        </div>
      )}

      <div className="bg-panel/70 border border-border rounded-xl p-3.5 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield size={15} className="text-accent" />
            <h4 className="text-xs font-semibold text-fg">Modalità di Rischio & Human-in-the-Loop</h4>
          </div>
          <span className="text-[10px] text-fg-muted font-mono">Sincronizzata con toolbar</span>
        </div>
        <p className="text-[11px] text-fg-muted leading-relaxed">
          Configura il comportamento di autorizzazione per i tool eseguiti dall'agent. Puoi cambiare modalità rapidamente anche tramite il
          selettore nella barra messaggi.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-2 pt-1">
          {MODES.map(({ mode, label, icon: Icon, tagline, description, color, selected, idle, dot }) => (
            <div
              key={mode}
              onClick={() => selectMode(mode)}
              className={`p-2.5 rounded-xl border transition cursor-pointer flex flex-col justify-between ${
                securityMode === mode ? selected : `bg-black/20 border-border ${idle}`
              }`}
            >
              <div>
                <div className="flex items-center justify-between mb-1">
                  <div className={`flex items-center gap-1.5 text-xs font-semibold ${color}`}>
                    <Icon size={13} />
                    <span>{label}</span>
                  </div>
                  {securityMode === mode && <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />}
                </div>
                <p className="text-[10px] text-fg-muted leading-snug">{description}</p>
              </div>
              <div className={`mt-2 text-[9px] font-medium uppercase tracking-wider ${color} opacity-80`}>{tagline}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-panel/70 border border-border rounded-xl p-3.5 space-y-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldAlert size={15} className="text-rose-400" />
            <h4 className="text-xs font-semibold text-fg">Tier 1: Guardrail Deterministici (Automatici)</h4>
          </div>
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">
            Attivo & Inviolabile
          </span>
        </div>
        <p className="text-[11px] text-fg-muted leading-relaxed">
          Questi comandi distruttivi sono <strong>categoricamente bloccati</strong> prima dell'esecuzione. Nessun prompt, modalità o
          parametro (incluso <code>confirm=true</code> simulato dal modello) può scavalcare questo blocco.
        </p>
        <div className="grid grid-cols-1 gap-1.5 pt-1 text-[10px] text-fg-muted">
          {BLOCKED_COMMANDS.map((text, idx) => (
            <div key={idx} className="flex items-center gap-1.5 p-1.5 rounded-lg bg-black/30 border border-border/60">
              <Lock size={11} className="text-rose-400 shrink-0" />
              <span>{text}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck size={15} className="text-emerald-400" />
            <h4 className="text-xs font-semibold text-fg">Tier 2: Permessi Tool Accordati (Human-in-the-Loop)</h4>
          </div>
          <button onClick={load} disabled={loading} className="p-1 text-fg-muted hover:text-fg transition rounded cursor-pointer" title="Aggiorna permessi">
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>

        <div className="space-y-2">
          <div className="text-[11px] font-semibold text-fg-muted uppercase tracking-wider">Permessi Permanenti (Always)</div>
          {loading ? (
            <div className="flex items-center justify-center p-4 text-xs text-fg-muted">
              <Loader2 size={14} className="animate-spin mr-2" />
              Caricamento permessi...
            </div>
          ) : permissions.always.length === 0 ? (
            <div className="p-3 rounded-xl border border-border bg-panel/40 text-center text-xs text-fg-muted">
              Nessun permesso permanente memorizzato. I tool ad alto rischio richiederanno sempre autorizzazione.
            </div>
          ) : (
            permissions.always.map((perm) => (
              <div
                key={perm.id}
                className="flex items-center justify-between gap-2 p-2.5 rounded-xl border border-border bg-panel/80 hover:border-accent/40 transition"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-bold text-emerald-300">{perm.tool_name}</span>
                    {perm.command_prefix && (
                      <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-black/40 border border-border text-fg-muted">
                        prefisso: {perm.command_prefix}
                      </span>
                    )}
                  </div>
                  <div className="text-[10px] text-fg-muted mt-0.5">
                    Scope: sempre · ID: #{perm.id} {perm.created_by ? `· da: ${perm.created_by}` : ''}
                  </div>
                </div>
                <button
                  onClick={() => revoke(() => revokePermission(perm.id), 'Permesso permanente revocato con successo.')}
                  className={revokeButton}
                  title="Revoca permesso permanente"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))
          )}
        </div>

        {sessions.length > 0 && (
          <div className="space-y-2 pt-2 border-t border-border">
            <div className="text-[11px] font-semibold text-fg-muted uppercase tracking-wider">Permessi di Sessione (Questa Chat)</div>
            {sessions.map(([threadId, tools]) => (
              <div key={threadId} className="flex items-center justify-between gap-2 p-2.5 rounded-xl border border-sky-500/20 bg-sky-950/10">
                <div className="min-w-0">
                  <div className="text-[11px] font-mono font-medium text-sky-300 truncate">Thread: {threadId}</div>
                  <div className="text-[10px] text-fg-muted mt-0.5">Tool consentiti: {tools.join(', ')}</div>
                </div>
                <button
                  onClick={() => revoke(() => revokeThreadPermissions(threadId), `Permessi per il thread "${threadId}" revocati.`)}
                  className={revokeButton}
                  title="Revoca permessi per questo thread"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
