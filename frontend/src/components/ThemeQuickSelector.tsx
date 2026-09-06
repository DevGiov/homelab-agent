import React, { useState, useRef, useEffect } from 'react';
import { Palette, Check, Sparkles, SunMedium, X } from 'lucide-react';
import { useTheme } from '../theme/ThemeContext';

export const ThemeQuickSelector: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const { theme, setTheme, isFrosted, setIsFrosted, hasGlow, setHasGlow, themes } = useTheme();
  const popoverRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Close when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        isOpen &&
        popoverRef.current &&
        !popoverRef.current.contains(event.target as Node) &&
        buttonRef.current &&
        !buttonRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen]);

  return (
    <div className="relative inline-block">
      {/* Trigger Button */}
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className={`p-2 rounded-lg transition-all duration-200 flex items-center justify-center cursor-pointer ${
          isOpen
            ? 'bg-accent text-white shadow-lg shadow-accent/25 scale-105 ring-1 ring-accent/50'
            : 'text-fg-muted hover:text-fg hover:bg-panel border border-transparent hover:border-border'
        }`}
        title="Selettore Temi & Effetti Visivi"
        aria-label="Cambia tema e trasparenze"
        aria-expanded={isOpen}
      >
        <Palette size={16} className="transition-transform duration-300 group-hover:rotate-12" />
      </button>

      {/* Popover */}
      {isOpen && (
        <div
          ref={popoverRef}
          className="absolute right-0 mt-2 w-72 sm:w-80 rounded-2xl shadow-2xl p-4 z-50 animate-in fade-in zoom-in-95 duration-200 border border-border bg-panel/95 backdrop-blur-2xl text-fg"
          style={{
            boxShadow: '0 20px 40px -15px rgba(0, 0, 0, 0.6), 0 0 0 1px var(--border)',
          }}
        >
          {/* Popover Header */}
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-border">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-md bg-accent/15 flex items-center justify-center text-accent">
                <Palette size={13} />
              </div>
              <span className="font-semibold text-xs text-fg tracking-wide uppercase">Temi & Aspetto</span>
            </div>
            <button
              onClick={() => setIsOpen(false)}
              className="p-1 rounded-md text-fg-muted hover:text-fg hover:bg-border/40 transition"
              title="Chiudi"
            >
              <X size={14} />
            </button>
          </div>

          {/* Theme Grid */}
          <div className="grid grid-cols-2 gap-2 mb-4 max-h-[220px] overflow-y-auto pr-0.5 custom-scrollbar">
            {themes.map((t) => {
              const isActive = theme === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setTheme(t.id)}
                  className={`flex flex-col gap-1.5 p-2 rounded-xl text-left transition-all duration-200 cursor-pointer border ${
                    isActive
                      ? 'border-accent bg-accent/10 shadow-sm shadow-accent/20 ring-1 ring-accent/40'
                      : 'border-border/60 hover:border-border hover:bg-panel-header/50'
                  }`}
                >
                  <div className="flex items-center justify-between w-full">
                    {/* 4-Color Swatch Preview */}
                    <div className="flex items-center h-3 w-16 rounded-full overflow-hidden border border-border shadow-inner">
                      <span className="h-full flex-1" style={{ backgroundColor: t.swatch[0] }} />
                      <span className="h-full flex-1" style={{ backgroundColor: t.swatch[1] }} />
                      <span className="h-full flex-1" style={{ backgroundColor: t.swatch[2] }} />
                      <span className="h-full flex-1" style={{ backgroundColor: t.swatch[3] }} />
                    </div>
                    {isActive && <Check size={12} className="text-accent shrink-0" />}
                  </div>
                  <span className="text-[11px] font-medium text-fg truncate">{t.name}</span>
                </button>
              );
            })}
          </div>

          {/* Effects Controls */}
          <div className="space-y-2 pt-2 border-t border-border">
            {/* Frosted Glass Toggle */}
            <div className="flex items-center justify-between p-2 rounded-xl bg-panel-header/40 border border-border/50">
              <div className="flex items-center gap-2">
                <Sparkles size={13} className={isFrosted ? 'text-accent' : 'text-fg-muted'} />
                <div className="flex flex-col">
                  <span className="text-xs font-medium text-fg">Frosted Glass</span>
                  <span className="text-[10px] text-fg-muted">Trasparenze & blur pannelli</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsFrosted(!isFrosted)}
                className={`w-9 h-5 rounded-full transition-colors relative cursor-pointer ${
                  isFrosted ? 'bg-accent' : 'bg-border'
                }`}
                aria-label="Toggle Frosted Glass"
              >
                <div
                  className={`w-3.5 h-3.5 rounded-full bg-white transition-transform duration-200 absolute top-[3px] left-[3px] shadow-sm ${
                    isFrosted ? 'translate-x-4' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>

            {/* Ambient Glow Toggle */}
            <div className="flex items-center justify-between p-2 rounded-xl bg-panel-header/40 border border-border/50">
              <div className="flex items-center gap-2">
                <SunMedium size={13} className={hasGlow ? 'text-accent' : 'text-fg-muted'} />
                <div className="flex flex-col">
                  <span className="text-xs font-medium text-fg">Ambient Glow</span>
                  <span className="text-[10px] text-fg-muted">Bagliori colorati di sfondo</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setHasGlow(!hasGlow)}
                className={`w-9 h-5 rounded-full transition-colors relative cursor-pointer ${
                  hasGlow ? 'bg-accent' : 'bg-border'
                }`}
                aria-label="Toggle Ambient Glow"
              >
                <div
                  className={`w-3.5 h-3.5 rounded-full bg-white transition-transform duration-200 absolute top-[3px] left-[3px] shadow-sm ${
                    hasGlow ? 'translate-x-4' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
