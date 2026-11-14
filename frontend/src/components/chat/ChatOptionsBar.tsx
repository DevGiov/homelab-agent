import React, { useEffect, useId, useRef, useState } from 'react';
import { Brain, ChevronDown, EyeOff, Globe, Lock, Shield, ShieldCheck, SlidersHorizontal, Zap, type LucideIcon } from 'lucide-react';
import type { SecurityMode, WebSearchMode } from '../../api/chat';
import type { ChatOptions } from '../../hooks/useChatOptions';
import type { ModelCatalog } from '../../hooks/useModelCatalog';
import { ModelSelector } from '../ModelSelector';
import { LABEL_CHIPS, LABEL_HINTS, LABEL_NAMES, LEVELS, type SensitivityLevel } from '../../utils/sensitivity';

interface Choice<T extends string> {
  value: T;
  label: string;
  hint: string;
  icon?: LucideIcon;
  /** Classi della scelta attiva e della chip quando non è il default (vuoto: aspetto neutro). */
  tone?: string;
}

const SECURITY_MODES: Choice<SecurityMode>[] = [
  {
    value: 'safest',
    label: 'Safest',
    icon: Shield,
    tone: 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300',
    hint: 'Ogni tool esterno chiede approvazione, tranne ricerca web e memoria.',
  },
  {
    value: 'normal',
    label: 'Normal',
    icon: ShieldCheck,
    hint: 'I tool di sola lettura partono da soli; scritture e comandi chiedono conferma.',
  },
  {
    value: 'dangerous',
    label: 'Dangerous',
    icon: Zap,
    tone: 'bg-rose-500/15 border-rose-500/40 text-rose-300',
    hint: 'Nessuna conferma: resta solo il blocco dei comandi distruttivi.',
  },
];

const WEB_MODES: Choice<WebSearchMode>[] = [
  { value: 'auto', label: 'Auto', hint: 'Ricerca preventiva solo per le domande informative, non per comandi e tool del homelab.' },
  { value: 'on', label: 'Sempre', hint: 'Ricerca preventiva prima di ogni risposta.' },
  { value: 'off', label: 'Mai', hint: 'Nessuna ricerca preventiva.' },
];

const LEVEL_CHOICES: Choice<SensitivityLevel>[] = LEVELS.map((level) => ({
  value: level,
  label: LABEL_NAMES[level],
  hint: LABEL_HINTS[level],
  tone: level === 'public' ? undefined : LABEL_CHIPS[level],
}));

// "Per fase": ogni fase del turno ragiona secondo la modalità; un numero sostituisce il budget delle fasi che ragionano
const BUDGETS = [
  { value: 'default', label: 'Per fase' },
  { value: '0', label: 'Spento' },
  { value: '2048', label: '2048 token' },
  { value: '8192', label: '8192 token' },
  { value: '32768', label: '32768 token' },
];

const NEUTRAL_ACTIVE = 'bg-accent/15 border-accent/40 text-accent';
const NEUTRAL_CHIP = 'bg-panel/60 border-border text-fg-muted';

function Segmented<T extends string>({ label, choices, value, onChange }: {
  label: string;
  choices: Choice<T>[];
  value: T;
  onChange: (value: T) => void;
}) {
  const current = choices.find((c) => c.value === value);
  return (
    <div className="space-y-1">
      <div className="text-xs font-semibold text-fg-muted">{label}</div>
      <div role="group" aria-label={label} className="flex gap-0.5 rounded-lg border border-border bg-bg/40 p-0.5">
        {choices.map(({ value: choice, label: text, icon: Icon, tone }) => {
          const selected = choice === value;
          return (
            <button
              key={choice}
              type="button"
              aria-pressed={selected}
              onClick={() => onChange(choice)}
              className={`flex-1 flex items-center justify-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition cursor-pointer ${
                selected ? tone || NEUTRAL_ACTIVE : 'border-transparent text-fg-muted hover:text-fg hover:bg-panel-hover'
              }`}
            >
              {Icon && <Icon size={12} aria-hidden="true" />}
              {text}
            </button>
          );
        })}
      </div>
      {current && <p className="text-xs text-fg-muted">{current.hint}</p>}
    </div>
  );
}

interface ChatOptionsBarProps {
  options: ChatOptions;
  models: ModelCatalog;
  /** Livello minimo della conversazione e chi lo cambia (useConversationLevel). */
  level?: SensitivityLevel;
  onLevelChange?: (level: SensitivityLevel) => void;
}

interface Change {
  key: string;
  text: string;
  icon: LucideIcon;
  tone: string;
}

/** Le scelte diverse dal default, da tenere sotto gli occhi anche con il pannello chiuso. */
function changesOf(options: ChatOptions, level?: SensitivityLevel): Change[] {
  const changes: Change[] = [];
  const security = SECURITY_MODES.find((m) => m.value === options.securityMode);
  if (security && options.securityMode !== 'normal') {
    changes.push({ key: 'security', text: security.label, icon: security.icon ?? Shield, tone: security.tone ?? NEUTRAL_CHIP });
  }
  if (level && level !== 'public') {
    changes.push({ key: 'level', text: `Dati ${LABEL_NAMES[level].toLowerCase()}`, icon: Lock, tone: LABEL_CHIPS[level] });
  }
  if (options.incognito) {
    changes.push({ key: 'incognito', text: 'Incognito', icon: EyeOff, tone: 'bg-purple-500/15 border-purple-500/40 text-purple-300' });
  }
  if (options.webSearch !== 'auto') {
    const web = WEB_MODES.find((m) => m.value === options.webSearch);
    changes.push({ key: 'web', text: `Web: ${web?.label.toLowerCase()}`, icon: Globe, tone: NEUTRAL_CHIP });
  }
  if (options.reasoningBudget !== undefined) {
    const budget = BUDGETS.find((b) => b.value === String(options.reasoningBudget));
    changes.push({ key: 'reasoning', text: `Ragionamento: ${(budget?.label ?? `${options.reasoningBudget} token`).toLowerCase()}`, icon: Brain, tone: NEUTRAL_CHIP });
  }
  return changes;
}

/**
 * Opzioni del prossimo invio: sicurezza, livello dei dati, ricerca web, incognito e ragionamento in un pannello; fuori
 * restano il modello e, come chip, solo le scelte diverse dal default.
 */
export const ChatOptionsBar: React.FC<ChatOptionsBarProps> = ({ options, models, level, onLevelChange }) => {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const budgetId = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const changes = changesOf(options, level);

  useEffect(() => {
    if (!open) return;
    panelRef.current?.querySelector<HTMLElement>('button, select')?.focus();
    const onPointer = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!panelRef.current?.contains(target) && !buttonRef.current?.contains(target)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div className="max-w-4xl mx-auto w-full flex items-center gap-1.5 flex-wrap">
      <div className="relative">
        <button
          ref={buttonRef}
          type="button"
          onClick={() => setOpen(!open)}
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition cursor-pointer ${
            open ? NEUTRAL_ACTIVE : 'glass-card border-border text-fg-muted hover:text-fg hover:border-accent/40'
          }`}
        >
          <SlidersHorizontal size={13} aria-hidden="true" />
          Opzioni
          <ChevronDown size={12} aria-hidden="true" className={`transition-transform ${open ? 'rotate-180' : ''}`} />
        </button>

        {open && (
          <div
            ref={panelRef}
            id={panelId}
            role="dialog"
            aria-label="Opzioni dell'invio"
            className="absolute bottom-full left-0 mb-2 z-50 w-[min(22rem,calc(100vw-2rem))] space-y-3 rounded-xl border border-border p-3 text-fg shadow-2xl"
            style={{ backgroundColor: 'var(--panel)' }}
          >
            <Segmented label="Sicurezza" choices={SECURITY_MODES} value={options.securityMode} onChange={options.setSecurityMode} />
            {level && onLevelChange && (
              <Segmented label="Dati della conversazione" choices={LEVEL_CHOICES} value={level} onChange={onLevelChange} />
            )}
            <Segmented label="Ricerca web" choices={WEB_MODES} value={options.webSearch} onChange={options.setWebSearch} />

            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={options.incognito}
                onChange={(e) => options.setIncognito(e.target.checked)}
                className="mt-0.5 rounded border-border bg-input-bg text-accent"
              />
              <span>
                <span className="block text-xs font-semibold text-fg-muted">Incognito</span>
                <span className="block text-xs text-fg-muted">Memoria a lungo termine spenta: nessun fatto richiamato né salvato.</span>
              </span>
            </label>

            <div className="space-y-1">
              <label htmlFor={budgetId} className="block text-xs font-semibold text-fg-muted">
                Ragionamento
              </label>
              <select
                id={budgetId}
                value={options.reasoningBudget === undefined ? 'default' : String(options.reasoningBudget)}
                onChange={(e) => options.setReasoningBudget(e.target.value === 'default' ? undefined : Number(e.target.value))}
                className="w-full rounded-lg border border-border bg-input-bg px-2 py-1 text-xs text-fg cursor-pointer"
              >
                {BUDGETS.map(({ value, label }) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}
      </div>

      {changes.map(({ key, text, icon: Icon, tone }) => (
        <button
          key={key}
          type="button"
          onClick={() => setOpen(true)}
          title="Cambia nelle opzioni"
          className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium cursor-pointer ${tone}`}
          data-testid={`option-change-${key}`}
        >
          <Icon size={11} aria-hidden="true" />
          {text}
        </button>
      ))}

      <div className="ml-auto min-w-0">
        <ModelSelector
          selectedModel={options.model}
          onSelectModel={options.setModel}
          modelDetails={models.modelDetails}
          activeProvider={models.activeProvider}
          onRefreshModels={models.refreshModels}
        />
      </div>
    </div>
  );
};
