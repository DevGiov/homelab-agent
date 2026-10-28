import React from 'react';
import { Search } from 'lucide-react';
import { ENTITY_TYPES, type Entity, type EntityType } from '../../api/memory';
import { ENTITY_TYPE_INFO } from './entityTypes';

interface EntityPanelProps {
  entities: Entity[];
  query: string;
  type: EntityType | '';
  selectedId?: number;
  onQueryChange: (value: string) => void;
  onTypeChange: (value: EntityType | '') => void;
  onSelect: (id: number | null) => void;
}

const inputClass =
  'bg-input-bg border border-input-border rounded-lg px-2 py-1.5 text-xs text-fg placeholder:text-fg-muted/60 focus:outline-none focus:border-accent';

/** Entità della memoria, le più citate per prime; la selezione filtra i fatti. */
export const EntityPanel: React.FC<EntityPanelProps> = ({ entities, query, type, selectedId, onQueryChange, onTypeChange, onSelect }) => (
  <div className="flex flex-col min-h-0 h-full">
    <div className="space-y-1.5 pb-2">
      <div className="relative">
        <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-fg-muted" />
        <input value={query} onChange={(e) => onQueryChange(e.target.value)} placeholder="Filtra entità" className={`${inputClass} w-full pl-7`} aria-label="Filtra entità" />
      </div>
      <select value={type} onChange={(e) => onTypeChange(e.target.value as EntityType | '')} className={`${inputClass} w-full`} aria-label="Tipo di entità">
        <option value="">Tutti i tipi</option>
        {ENTITY_TYPES.map((t) => (
          <option key={t} value={t}>
            {ENTITY_TYPE_INFO[t].label}
          </option>
        ))}
      </select>
    </div>

    <ul className="flex-1 overflow-y-auto space-y-0.5 custom-scrollbar -mx-1 px-1" aria-label="Entità">
      {entities.length === 0 && <li className="text-[11px] text-fg-muted py-3 text-center">Nessuna entità.</li>}
      {entities.map((e) => {
        const { icon: Icon, label } = ENTITY_TYPE_INFO[e.type] ?? ENTITY_TYPE_INFO.other;
        const active = e.id === selectedId;
        return (
          <li key={e.id}>
            <button
              onClick={() => onSelect(active ? null : e.id)}
              aria-pressed={active}
              className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-left transition cursor-pointer ${
                active ? 'bg-accent/15 text-fg' : 'text-fg-muted hover:text-fg hover:bg-panel-hover'
              }`}
            >
              <Icon size={13} className="shrink-0" aria-label={label} />
              <span className="flex-1 truncate">{e.name}</span>
              <span className="tabular-nums text-[11px] text-fg-muted">{e.fact_count}</span>
            </button>
          </li>
        );
      })}
    </ul>
  </div>
);
