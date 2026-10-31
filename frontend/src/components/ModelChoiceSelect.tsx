import React from 'react';
import { useModelCatalog } from '../hooks/useModelCatalog';
import { LOADED_MODEL } from '../utils/modelChoice';

interface ModelChoiceSelectProps {
  /** '' = default del server, LOADED_MODEL = il modello caricato quando il lavoro parte, altrimenti il nome. */
  value: string;
  onChange: (value: string) => void;
  className?: string;
  'aria-label'?: string;
}

/** Selettore del modello per i lavori in background: default, modello caricato al momento o un modello preciso. */
export const ModelChoiceSelect: React.FC<ModelChoiceSelectProps> = ({ value, onChange, className = '', ...rest }) => {
  const { modelDetails, loadedModel } = useModelCatalog();
  const ids = modelDetails.map((m) => m.id);
  // Un modello salvato che il server non elenca più resta visibile e selezionato
  if (value && value !== LOADED_MODEL && !ids.includes(value)) ids.unshift(value);
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={className} aria-label={rest['aria-label']}>
      <option value="">Default del server</option>
      <option value={LOADED_MODEL}>Modello caricato al momento{loadedModel ? ` (ora: ${loadedModel})` : ''}</option>
      {ids.map((id) => (
        <option key={id} value={id}>
          {id}
        </option>
      ))}
    </select>
  );
};
