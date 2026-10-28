import React from 'react';
import { X } from 'lucide-react';
import type { EntityRef } from '../../api/memory';
import { ENTITY_TYPE_INFO } from './entityTypes';

interface EntityChipProps {
  entity: EntityRef;
  active?: boolean;
  onClick?: () => void;
  onRemove?: () => void;
  /** Testo aggiuntivo dopo il nome, per esempio i fatti in comune. */
  suffix?: string;
}

/** Entità con l'icona del suo tipo; cliccabile per filtrare, rimovibile in modifica. */
export const EntityChip: React.FC<EntityChipProps> = ({ entity, active, onClick, onRemove, suffix }) => {
  const { icon: Icon, label } = ENTITY_TYPE_INFO[entity.type] ?? ENTITY_TYPE_INFO.other;
  const className = `inline-flex items-center gap-1 max-w-full px-1.5 py-0.5 rounded-md border text-[11px] transition ${
    active ? 'bg-accent/15 border-accent/50 text-fg' : 'bg-panel-header/60 border-border text-fg-muted'
  } ${onClick ? 'hover:text-fg hover:border-accent/40 cursor-pointer' : ''}`;
  const content = (
    <>
      <Icon size={11} className="shrink-0" aria-label={label} />
      <span className="truncate">{entity.name}</span>
      {suffix && <span className="text-fg-muted">{suffix}</span>}
    </>
  );

  if (onRemove) {
    return (
      <span className={className} title={label}>
        {content}
        <button type="button" onClick={onRemove} className="ml-0.5 text-fg-muted hover:text-rose-400 cursor-pointer" aria-label={`Rimuovi ${entity.name}`}>
          <X size={11} />
        </button>
      </span>
    );
  }
  return onClick ? (
    <button type="button" onClick={onClick} className={className} title={label}>
      {content}
    </button>
  ) : (
    <span className={className} title={label}>
      {content}
    </span>
  );
};
