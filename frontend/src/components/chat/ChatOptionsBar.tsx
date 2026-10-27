import React from 'react';
import { Brain, EyeOff, Globe, Shield, ShieldCheck, Zap, type LucideIcon } from 'lucide-react';
import type { SecurityMode, WebSearchMode } from '../../api/chat';
import type { ChatOptions } from '../../hooks/useChatOptions';
import type { ModelCatalog } from '../../hooks/useModelCatalog';
import { ModelSelector } from '../ModelSelector';

const SECURITY_MODES: Array<{ mode: SecurityMode; label: string; icon: LucideIcon; active: string; iconActive: string; title: string }> = [
  {
    mode: 'safest',
    label: 'Safest',
    icon: Shield,
    active: 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-xs',
    iconActive: 'text-emerald-400',
    title: 'Safest: Qualunque tool esterno richiede approvazione esplicita (eccetto web search e memoria)',
  },
  {
    mode: 'normal',
    label: 'Normal',
    icon: ShieldCheck,
    active: 'bg-accent/20 text-accent border border-accent/40 shadow-xs',
    iconActive: 'text-accent',
    title: 'Normal: I tool VIEW (lettura) sono automatici; i comandi di scrittura/shell richiedono conferma',
  },
  {
    mode: 'dangerous',
    label: 'Dangerous',
    icon: Zap,
    active: 'bg-rose-500/20 text-rose-300 border border-rose-500/40 shadow-xs',
    iconActive: 'text-rose-400',
    title: 'Dangerous: Esecuzione autonoma senza prompt UI (salvaguardia Tier 1 rm -rf / resta comunque attiva)',
  },
];

const WEB_SEARCH: Record<WebSearchMode, { label: string; button: string; icon: string; title: string }> = {
  auto: {
    label: 'Web Auto',
    button: 'bg-sky-500/15 border-sky-500/50 text-sky-400 ring-1 ring-sky-500/30 shadow-sky-500/10',
    icon: 'text-sky-400',
    title: 'Ricerca Web Automatica (attiva per query informative/generiche, esclusa per comandi e tool homelab)',
  },
  on: {
    label: 'Web ON',
    button: 'bg-emerald-500/20 border-emerald-500 text-emerald-400 ring-1 ring-emerald-500/50 shadow-emerald-500/20',
    icon: 'text-emerald-400',
    title: 'Ricerca Web Forzata (prefetch sempre attivo prima di rispondere)',
  },
  off: {
    label: 'Web OFF',
    button: 'glass-card border-border text-fg-muted hover:text-fg hover:border-accent/40',
    icon: 'text-fg-muted',
    title: 'Ricerca Web Disattivata (nessuna ricerca web preventiva)',
  },
};

const BUDGETS = [
  { value: 'default', label: 'Budget: Default' },
  { value: '0', label: 'Disable (0t)' },
  { value: '2048', label: 'Balanced (2048t)' },
  { value: '8192', label: 'Deep Think (8192t)' },
  { value: '-1', label: 'Unlimited (-1)' },
];

/** Opzioni del prossimo invio: sicurezza, incognito, ricerca web, modello e budget di reasoning. */
export const ChatOptionsBar: React.FC<{ options: ChatOptions; models: ModelCatalog }> = ({ options, models }) => {
  const web = WEB_SEARCH[options.webSearch];

  return (
    <div className="max-w-4xl mx-auto w-full flex justify-end gap-2 items-center flex-wrap">
      <div className="flex items-center glass-card border border-border rounded-lg p-0.5 text-[11px] gap-0.5 shadow-sm">
        {SECURITY_MODES.map(({ mode, label, icon: Icon, active, iconActive, title }) => {
          const selected = options.securityMode === mode;
          return (
            <button
              key={mode}
              type="button"
              onClick={() => options.setSecurityMode(mode)}
              className={`flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium transition cursor-pointer ${
                selected ? active : 'text-fg-muted hover:text-fg hover:bg-white/5'
              }`}
              title={title}
            >
              <Icon size={11} className={selected ? iconActive : 'text-fg-muted'} />
              <span>{label}</span>
            </button>
          );
        })}
      </div>

      <button
        type="button"
        onClick={() => options.setIncognito(!options.incognito)}
        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium border transition cursor-pointer shadow-sm ${
          options.incognito
            ? 'bg-purple-950/70 border-purple-500 text-purple-200 shadow-purple-950/50 ring-1 ring-purple-500/50'
            : 'glass-card border-border text-fg-muted hover:text-fg hover:border-accent/40'
        }`}
        title={
          options.incognito
            ? 'Modalità Incognito attiva (nessun fatto salvato)'
            : 'Attiva Modalità Incognito (disabilita estrazione e memoria)'
        }
      >
        <EyeOff size={12} className={options.incognito ? 'text-purple-400' : 'text-fg-muted shrink-0'} />
        <span className="text-[11px] font-sans">{options.incognito ? 'Incognito ON' : 'Incognito'}</span>
      </button>

      <button
        type="button"
        onClick={options.cycleWebSearch}
        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium border transition cursor-pointer shadow-sm ${web.button}`}
        title={web.title}
      >
        <Globe size={12} className={`${web.icon} shrink-0`} />
        <span className="text-[11px] font-sans">{web.label}</span>
      </button>

      <ModelSelector
        selectedModel={options.model}
        onSelectModel={options.setModel}
        modelDetails={models.modelDetails}
        activeProvider={models.activeProvider}
        onRefreshModels={models.refreshModels}
      />

      <div className="flex items-center glass-card border border-border rounded-lg px-2 py-1 text-[11px] gap-1.5 text-fg-muted hover:border-accent/40 w-max shadow-sm">
        <Brain size={12} className="text-purple-400 shrink-0" />
        <select
          value={options.reasoningBudget === undefined ? 'default' : String(options.reasoningBudget)}
          onChange={(e) => options.setReasoningBudget(e.target.value === 'default' ? undefined : Number(e.target.value))}
          className="bg-transparent text-[11px] text-fg focus:outline-none cursor-pointer"
          title="Reasoning Token Budget"
        >
          {BUDGETS.map(({ value, label }) => (
            <option key={value} value={value} className="bg-panel text-fg">
              {label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
};
