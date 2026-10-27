import React from 'react';

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Colore della traccia quando è attivo, es. `peer-checked:bg-emerald-500`. */
  activeClass?: string;
  size?: 'sm' | 'md';
  disabled?: boolean;
  title?: string;
}

/** Interruttore on/off con i colori del tema. */
export const Toggle: React.FC<ToggleProps> = ({ checked, onChange, activeClass = 'peer-checked:bg-accent', size = 'md', disabled, title }) => {
  const track = size === 'sm' ? 'w-8 h-4 after:h-3 after:w-3' : 'w-9 h-5 after:h-4 after:w-4';
  return (
    <label className={`relative inline-flex items-center cursor-pointer ${disabled ? 'opacity-50 pointer-events-none' : ''}`} title={title}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="sr-only peer" />
      <div
        className={`${track} bg-border rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:shadow-sm after:transition-all ${activeClass}`}
      />
    </label>
  );
};
