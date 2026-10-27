import React from 'react';
import { PRESET_COLORS } from './formStyles';

interface ColorPickerProps {
  value: string;
  onChange: (color: string) => void;
  colors?: string[];
  size?: 'sm' | 'md';
}

/** Colori predefiniti più un selettore libero. */
export const ColorPicker: React.FC<ColorPickerProps> = ({ value, onChange, colors = PRESET_COLORS, size = 'sm' }) => {
  const swatch = size === 'md' ? 'w-7 h-7' : 'w-6 h-6';
  return (
    <div className="flex flex-wrap items-center gap-2 pt-0.5">
      {colors.map((color) => (
        <button
          key={color}
          type="button"
          onClick={() => onChange(color)}
          className={`${swatch} rounded-full border transition cursor-pointer ${
            value.toLowerCase() === color ? 'scale-110 border-white ring-2 ring-accent shadow-md' : 'border-transparent hover:scale-105'
          }`}
          style={{ backgroundColor: color }}
          aria-label={`Colore ${color}`}
        />
      ))}
      <input
        type="color"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`${size === 'md' ? 'w-8 h-8 rounded-full' : 'w-7 h-7 rounded'} border border-border cursor-pointer bg-transparent`}
        title="Colore personalizzato"
      />
    </div>
  );
};
