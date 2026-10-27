import React from 'react';
import { Check, Palette, Sparkles } from 'lucide-react';
import { useTheme } from '../../theme/useTheme';

const Switch: React.FC<{ label: string; description: string; checked: boolean; onChange: (value: boolean) => void }> = ({
  label,
  description,
  checked,
  onChange,
}) => (
  <div className="flex items-center justify-between p-3 rounded-xl glass-card border border-border">
    <div className="flex flex-col pr-4">
      <span className="text-xs font-medium text-fg">{label}</span>
      <span className="text-[11px] text-fg-muted">{description}</span>
    </div>
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`w-11 h-6 rounded-full transition-colors relative cursor-pointer shrink-0 ${checked ? 'bg-accent' : 'bg-border'}`}
    >
      <div
        className={`w-4 h-4 rounded-full bg-white transition-transform duration-200 absolute top-1 left-1 shadow-sm ${
          checked ? 'translate-x-5' : 'translate-x-0'
        }`}
      />
    </button>
  </div>
);

export const AppearanceTab: React.FC = () => {
  const { theme, setTheme, isFrosted, setIsFrosted, hasGlow, setHasGlow, themes } = useTheme();

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <label className="text-xs font-medium text-fg flex items-center gap-1.5">
          <Palette size={13} className="text-accent" />
          Tema Interfaccia
        </label>
        <div className="grid grid-cols-2 gap-2.5">
          {themes.map((t) => {
            const isActive = theme === t.id;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setTheme(t.id)}
                className={`flex flex-col gap-2 p-3 rounded-xl text-left transition-all duration-200 cursor-pointer border ${
                  isActive
                    ? 'border-accent bg-accent/10 shadow-md shadow-accent/15 ring-1 ring-accent/50'
                    : 'glass-card border-border/60 hover:border-border hover:bg-panel-header/50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center h-3.5 w-20 rounded-full overflow-hidden border border-border shadow-inner">
                    {t.swatch.map((color, idx) => (
                      <span key={idx} className="h-full flex-1" style={{ backgroundColor: color }} />
                    ))}
                  </div>
                  {isActive && <Check size={14} className="text-accent shrink-0" />}
                </div>
                <div>
                  <div className="text-xs font-semibold text-fg">{t.name}</div>
                  <div className="text-[10px] text-fg-muted line-clamp-1">{t.description}</div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="space-y-2.5 pt-2 border-t border-border">
        <label className="text-xs font-medium text-fg flex items-center gap-1.5">
          <Sparkles size={13} className="text-accent" />
          Effetti Visivi & Glassmorphism
        </label>
        <Switch
          label="Frosted Glass (Trasparenze)"
          description="Applica sfocatura dinamica (blur) e trasparenze a pannelli, sidebar, header e modali."
          checked={isFrosted}
          onChange={setIsFrosted}
        />
        <Switch
          label="Ambient Glow (Bagliore di Sfondo)"
          description="Attiva orbi luminosi fluttuanti coordinati al tema che traspaiono attraverso il vetro."
          checked={hasGlow}
          onChange={setHasGlow}
        />
      </div>
    </div>
  );
};
