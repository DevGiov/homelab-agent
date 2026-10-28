import React, { useState } from 'react';
import { Loader2, Plus } from 'lucide-react';
import { ENTITY_TYPES, type Entity, type EntityRef, type EntityType, type FactInput } from '../../api/memory';
import { EntityChip } from './EntityChip';
import { ENTITY_TYPE_INFO } from './entityTypes';

interface FactEditorProps {
  initial?: FactInput;
  /** Entità già note: suggerite mentre si scrive, con il loro tipo. */
  known: Entity[];
  submitLabel: string;
  onSubmit: (input: FactInput) => Promise<boolean>;
  onCancel: () => void;
}

const inputClass =
  'bg-input-bg border border-input-border rounded-lg px-2 py-1.5 text-xs text-fg placeholder:text-fg-muted/60 focus:outline-none focus:border-accent';

/** Testo del fatto ed entità che cita, per un fatto nuovo o in modifica. */
export const FactEditor: React.FC<FactEditorProps> = ({ initial, known, submitLabel, onSubmit, onCancel }) => {
  const [content, setContent] = useState(initial?.content ?? '');
  const [entities, setEntities] = useState<EntityRef[]>(initial?.entities ?? []);
  const [name, setName] = useState('');
  const [type, setType] = useState<EntityType>('other');
  const [isSaving, setIsSaving] = useState(false);

  const changeName = (value: string) => {
    setName(value);
    const match = known.find((e) => e.name.toLowerCase() === value.trim().toLowerCase());
    if (match) setType(match.type);
  };

  const addEntity = () => {
    const clean = name.trim();
    if (!clean || entities.some((e) => e.name.toLowerCase() === clean.toLowerCase())) return;
    setEntities([...entities, { name: clean, type }]);
    setName('');
    setType('other');
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!content.trim() || isSaving) return;
    setIsSaving(true);
    const ok = await onSubmit({ content: content.trim(), entities });
    setIsSaving(false);
    if (ok) onCancel();
  };

  return (
    <form onSubmit={submit} className="space-y-2">
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={2}
        placeholder="Un fatto da ricordare, comprensibile da solo (es. 'Il NAS Synology ha IP 192.168.1.20')"
        className={`${inputClass} w-full resize-y leading-relaxed`}
        aria-label="Testo del fatto"
        autoFocus
      />
      <div className="flex flex-wrap items-center gap-1">
        {entities.map((entity) => (
          <EntityChip key={entity.name} entity={entity} onRemove={() => setEntities(entities.filter((e) => e !== entity))} />
        ))}
        {entities.length === 0 && <span className="text-[11px] text-fg-muted">Nessuna entità</span>}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <input
          value={name}
          onChange={(e) => changeName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              addEntity();
            }
          }}
          list="memory-known-entities"
          placeholder="Entità (es. Debian, CT 125)"
          className={`${inputClass} flex-1 min-w-[10rem]`}
          aria-label="Nome dell'entità"
        />
        <datalist id="memory-known-entities">
          {known.map((e) => (
            <option key={e.id} value={e.name} />
          ))}
        </datalist>
        <select value={type} onChange={(e) => setType(e.target.value as EntityType)} className={inputClass} aria-label="Tipo dell'entità">
          {ENTITY_TYPES.map((t) => (
            <option key={t} value={t}>
              {ENTITY_TYPE_INFO[t].label}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={addEntity}
          disabled={!name.trim()}
          className="p-1.5 rounded-lg border border-border text-fg-muted hover:text-fg hover:bg-panel-hover disabled:opacity-40 cursor-pointer"
          title="Aggiungi entità"
        >
          <Plus size={13} />
        </button>
      </div>
      <div className="flex justify-end gap-1.5">
        <button type="button" onClick={onCancel} className="px-3 py-1 rounded-lg text-xs text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer">
          Annulla
        </button>
        <button
          type="submit"
          disabled={!content.trim() || isSaving}
          className="px-3 py-1 rounded-lg bg-accent text-white text-xs font-semibold disabled:opacity-40 flex items-center gap-1 cursor-pointer"
        >
          {isSaving && <Loader2 size={12} className="animate-spin" />}
          {submitLabel}
        </button>
      </div>
    </form>
  );
};
