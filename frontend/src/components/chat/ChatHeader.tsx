import React from 'react';
import { Activity, Bot, Menu, Play } from 'lucide-react';
import type { AgentMode } from '../../api/chat';
import { ThemeQuickSelector } from '../ThemeQuickSelector';

const MODES = ['auto', 'chat', 'ask', 'act', 'plan'] as const;

interface ChatHeaderProps {
  title: string;
  mode: AgentMode | 'auto';
  onModeChange: (mode: AgentMode | 'auto') => void;
  execute: boolean;
  onExecuteChange: (execute: boolean) => void;
  onOpenMobileSidebar?: () => void;
  onOpenMobileToolLog?: () => void;
}

export const ChatHeader: React.FC<ChatHeaderProps> = ({
  title,
  mode,
  onModeChange,
  execute,
  onExecuteChange,
  onOpenMobileSidebar,
  onOpenMobileToolLog,
}) => (
  <div className="h-14 border-b border-border glass-header px-2.5 sm:px-6 flex items-center justify-between z-10 shrink-0 gap-2">
    <div className="flex items-center gap-2 min-w-0 shrink-0 sm:shrink">
      {onOpenMobileSidebar && (
        <button
          onClick={onOpenMobileSidebar}
          className="md:hidden p-1.5 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition shrink-0 cursor-pointer"
          title="Apri barra laterale conversazioni"
        >
          <Menu size={20} />
        </button>
      )}

      {/* Logo Bot: visibile solo da sm in su per risparmiare spazio su mobile */}
      <div className="hidden sm:flex w-8 h-8 rounded-full bg-gradient-to-tr from-accent to-accent-hover items-center justify-center text-white shadow-md shadow-accent/20 shrink-0">
        <Bot size={18} />
      </div>

      {/* Titolo Thread: visibile solo da md in su su desktop */}
      <div className="hidden md:block truncate max-w-xs">
        <h2 className="text-xs sm:text-sm font-semibold text-fg truncate" title={title}>
          {title}
        </h2>
        <p className="text-[10px] sm:text-[11px] text-fg-muted truncate">Main Agent Engine</p>
      </div>
    </div>

    {/* Mode Selector & Controls */}
    <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
      {/* Desktop Mode Pills */}
      <div className="hidden sm:flex bg-panel/80 border border-border rounded-lg p-1 items-center gap-1 text-xs shrink-0">
        <span className="text-fg-muted text-[11px] px-2 font-medium">Mode:</span>
        {MODES.map((modeOption) => (
          <button
            key={modeOption}
            onClick={() => onModeChange(modeOption)}
            className={`px-2.5 py-1 rounded-md text-xs font-medium capitalize transition cursor-pointer ${
              mode === modeOption
                ? 'bg-accent text-white shadow-md shadow-accent/25'
                : 'text-fg-muted hover:text-fg hover:bg-border/40'
            }`}
          >
            {modeOption}
          </button>
        ))}
      </div>

      {/* Mobile Mode Dropdown: etichette ultra compatte */}
      <div className="sm:hidden shrink-0">
        <select
          value={mode}
          onChange={(e) => onModeChange(e.target.value as AgentMode | 'auto')}
          className="bg-panel border border-border rounded-lg px-2 py-1 text-xs text-fg focus:outline-none focus:border-accent capitalize"
        >
          {MODES.map((modeOption) => (
            <option key={modeOption} value={modeOption}>
              {modeOption[0].toUpperCase() + modeOption.slice(1)}
            </option>
          ))}
        </select>
      </div>

      {/* Execute Toggle: compatto su mobile */}
      <label
        className="flex items-center gap-1 text-xs text-fg-muted cursor-pointer bg-panel/80 border border-border px-2 sm:px-2.5 py-1 sm:py-1.5 rounded-lg hover:border-accent/40 transition shrink-0"
        title={execute ? 'Esecuzione automatica attiva' : 'Preview / Dry-run'}
      >
        <input
          type="checkbox"
          checked={execute}
          onChange={(e) => onExecuteChange(e.target.checked)}
          className="rounded bg-input-bg border-border text-accent focus:ring-0 sr-only sm:not-sr-only"
        />
        <Play size={12} className={execute ? 'text-emerald-400' : 'text-fg-muted'} />
        <span className="text-[10px] sm:text-[11px] hidden sm:inline">Execute</span>
      </label>

      {/* Quick Theme Selector */}
      <div className="shrink-0">
        <ThemeQuickSelector />
      </div>

      {/* Mobile Diagnostics Button: sempre visibile e ben spaziato */}
      {onOpenMobileToolLog && (
        <button
          onClick={onOpenMobileToolLog}
          className="md:hidden p-1.5 text-accent hover:text-white bg-accent/15 hover:bg-accent border border-accent/30 rounded-lg transition shrink-0 flex items-center justify-center cursor-pointer shadow-sm"
          title="Apri Diagnostica"
          aria-label="Apri Diagnostica"
        >
          <Activity size={17} />
        </button>
      )}
    </div>
  </div>
);
