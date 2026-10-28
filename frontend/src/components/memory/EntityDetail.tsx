import React, { useState } from 'react';
import { Combine, Pencil, Trash2, X } from 'lucide-react';
import { ENTITY_TYPES, type Entity, type EntityDetail as Detail, type EntityRef, type EntityType } from '../../api/memory';
import { EntityChip } from './EntityChip';
import { ENTITY_TYPE_INFO } from './entityTypes';

interface EntityDetailProps {
  entity: Detail;
  /** Candidate per l'unione: tutte le altre entità. */
  others: Entity[];
  onClose: () => void;
  onSelect: (id: number) => void;
  onEdit: (input: EntityRef) => Promise<boolean>;
  onMerge: (target: Entity) => void;
  onDelete: () => void;
}

const inputClass = 'bg-input-bg border border-input-border rounded-lg px-2 py-1 text-xs text-fg focus:outline-none focus:border-accent';
const iconButton = 'p-1.5 rounded-lg text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer';

/** Entità selezionata: rinomina e tipo, unione in un'altra entità, eliminazione ed entità in relazione. */
export const EntityDetail: React.FC<EntityDetailProps> = ({ entity, others, onClose, onSelect, onEdit, onMerge, onDelete }) => {
  const [mode, setMode] = useState<'view' | 'edit' | 'merge'>('view');
  const [name, setName] = useState(entity.name);
  const [type, setType] = useState<EntityType>(entity.type);
  const [target, setTarget] = useState('');
  const { icon: Icon, label } = ENTITY_TYPE_INFO[entity.type] ?? ENTITY_TYPE_INFO.other;

  const startEdit = () => {
    setName(entity.name);
    setType(entity.type);
    setMode('edit');
  };

  return (
    <section className="rounded-xl border border-accent/30 bg-accent/5 p-3 space-y-2" aria-label={`Entità ${entity.name}`}>
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-lg bg-accent/15 text-accent flex items-center justify-center shrink-0">
          <Icon size={16} />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-semibold text-fg truncate">{entity.name}</h2>
          <p className="text-[11px] text-fg-muted">
            {label} · {entity.fact_count} {entity.fact_count === 1 ? 'fatto' : 'fatti'}
          </p>
        </div>
        <button onClick={startEdit} className={iconButton} title="Rinomina o cambia tipo">
          <Pencil size={13} />
        </button>
        <button onClick={() => setMode('merge')} className={iconButton} title="Unisci in un'altra entità" disabled={others.length === 0}>
          <Combine size={13} />
        </button>
        <button onClick={onDelete} className={`${iconButton} hover:text-rose-400`} title="Elimina entità (i fatti restano)">
          <Trash2 size={13} />
        </button>
        <button onClick={onClose} className={iconButton} title="Mostra tutti i fatti">
          <X size={14} />
        </button>
      </div>

      {mode === 'edit' && (
        <form
          className="flex flex-wrap gap-1.5"
          onSubmit={async (e) => {
            e.preventDefault();
            if (name.trim() && (await onEdit({ name: name.trim(), type }))) setMode('view');
          }}
        >
          <input value={name} onChange={(e) => setName(e.target.value)} className={`${inputClass} flex-1 min-w-[10rem]`} aria-label="Nome" autoFocus />
          <select value={type} onChange={(e) => setType(e.target.value as EntityType)} className={inputClass} aria-label="Tipo">
            {ENTITY_TYPES.map((t) => (
              <option key={t} value={t}>
                {ENTITY_TYPE_INFO[t].label}
              </option>
            ))}
          </select>
          <button type="submit" className="px-2.5 py-1 rounded-lg bg-accent text-white text-xs font-semibold cursor-pointer">
            Salva
          </button>
          <button type="button" onClick={() => setMode('view')} className="px-2 py-1 rounded-lg text-xs text-fg-muted hover:text-fg cursor-pointer">
            Annulla
          </button>
        </form>
      )}

      {mode === 'merge' && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-fg-muted">Unisci in</span>
          <select value={target} onChange={(e) => setTarget(e.target.value)} className={`${inputClass} flex-1 min-w-[10rem]`} aria-label="Entità di destinazione">
            <option value="">Scegli un'entità…</option>
            {others.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name} ({o.fact_count})
              </option>
            ))}
          </select>
          <button
            onClick={() => {
              const chosen = others.find((o) => String(o.id) === target);
              if (chosen) onMerge(chosen);
            }}
            disabled={!target}
            className="px-2.5 py-1 rounded-lg bg-accent text-white text-xs font-semibold disabled:opacity-40 cursor-pointer"
          >
            Unisci
          </button>
          <button onClick={() => setMode('view')} className="px-2 py-1 rounded-lg text-xs text-fg-muted hover:text-fg cursor-pointer">
            Annulla
          </button>
        </div>
      )}

      {entity.related.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-[11px] text-fg-muted mr-0.5">In relazione con</span>
          {entity.related.map((r) => (
            <EntityChip key={r.id} entity={r} suffix={`· ${r.shared}`} onClick={() => onSelect(r.id)} />
          ))}
        </div>
      )}
    </section>
  );
};
