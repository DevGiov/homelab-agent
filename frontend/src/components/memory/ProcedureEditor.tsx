import React, { useState } from 'react';
import { Loader2 } from 'lucide-react';
import type { ProcedureInput, ProcedureKind } from '../../api/memory';
import { KIND_LABELS } from './procedureKinds';

interface ProcedureEditorProps {
  initial?: ProcedureInput;
  /** Il tipo si sceglie solo per una procedura nuova. */
  kindLocked?: boolean;
  tools: string[];
  submitLabel: string;
  onSubmit: (input: ProcedureInput) => Promise<boolean>;
  onCancel: () => void;
}

const inputClass =
  'bg-input-bg border border-input-border rounded-lg px-2 py-1.5 text-xs text-fg placeholder:text-fg-muted/60 focus:outline-none focus:border-accent';

/** Tipo, tool (per le note), titolo e contenuto di una procedura nuova o in modifica. */
export const ProcedureEditor: React.FC<ProcedureEditorProps> = ({ initial, kindLocked, tools, submitLabel, onSubmit, onCancel }) => {
  const [kind, setKind] = useState<ProcedureKind>(initial?.kind ?? 'tool_note');
  const [toolName, setToolName] = useState(initial?.tool_name ?? '');
  const [title, setTitle] = useState(initial?.title ?? '');
  const [content, setContent] = useState(initial?.content ?? '');
  const [isSaving, setIsSaving] = useState(false);
  const valid = title.trim() && content.trim() && (kind !== 'tool_note' || toolName.trim());

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid || isSaving) return;
    setIsSaving(true);
    const ok = await onSubmit({ kind, title: title.trim(), content: content.trim(), tool_name: kind === 'tool_note' ? toolName.trim() : null });
    setIsSaving(false);
    if (ok) onCancel();
  };

  return (
    <form onSubmit={submit} className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        <select value={kind} onChange={(e) => setKind(e.target.value as ProcedureKind)} disabled={kindLocked} className={inputClass} aria-label="Tipo di procedura">
          {Object.entries(KIND_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        {kind === 'tool_note' && (
          <>
            <input
              value={toolName}
              onChange={(e) => setToolName(e.target.value)}
              list="procedure-tools"
              placeholder="Tool (es. proxmox-mcp__exec_lxc_command)"
              className={`${inputClass} flex-1 min-w-[12rem]`}
              aria-label="Tool della nota"
            />
            <datalist id="procedure-tools">
              {tools.map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>
          </>
        )}
      </div>
      <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Titolo breve" className={`${inputClass} w-full`} aria-label="Titolo della procedura" autoFocus />
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={kind === 'plan_template' ? 5 : 2}
        placeholder={kind === 'plan_template' ? '1. primo passo con il tool…\n2. …' : "Come usare il tool (es. 'Su CT 125 riavvia con docker compose, non systemctl')"}
        className={`${inputClass} w-full resize-y leading-relaxed font-mono`}
        aria-label="Contenuto della procedura"
      />
      <div className="flex justify-end gap-1.5">
        <button type="button" onClick={onCancel} className="px-3 py-1 rounded-lg text-xs text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer">
          Annulla
        </button>
        <button type="submit" disabled={!valid || isSaving} className="px-3 py-1 rounded-lg bg-accent text-white text-xs font-semibold disabled:opacity-40 flex items-center gap-1 cursor-pointer">
          {isSaving && <Loader2 size={12} className="animate-spin" />}
          {submitLabel}
        </button>
      </div>
    </form>
  );
};
