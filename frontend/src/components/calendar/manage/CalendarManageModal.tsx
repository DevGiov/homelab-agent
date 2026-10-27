import React, { useState } from 'react';
import { Calendar as CalIcon, Globe, Plus, Upload, X, type LucideIcon } from 'lucide-react';
import type { CalendarItem } from '../../../api/calendar';
import { useFeedback } from '../../../hooks/useFeedback';
import { formatApiError } from '../../../utils/error';
import { CalendarListTab } from './CalendarListTab';
import { ImportFileForm } from './ImportFileForm';
import { ImportUrlForm } from './ImportUrlForm';
import { NewCalendarForm } from './NewCalendarForm';
import type { Submit } from './types';

type Tab = 'list' | 'new' | 'url' | 'file';

interface CalendarManageModalProps {
  calendars: CalendarItem[];
  onClose: () => void;
  onCalendarsUpdated: () => void;
}

/** Gestione dei calendari: elenco, creazione, sottoscrizione a feed e import di file .ics. */
export const CalendarManageModal: React.FC<CalendarManageModalProps> = ({ calendars, onClose, onCalendarsUpdated }) => {
  const [activeTab, setActiveTab] = useState<Tab>('list');
  const [isBusy, setIsBusy] = useState(false);
  const { feedback, notify, clear } = useFeedback();

  const submit: Submit = async (action, failure) => {
    setIsBusy(true);
    try {
      notify('success', await action());
      onCalendarsUpdated();
      setActiveTab('list');
      return true;
    } catch (err) {
      notify('error', formatApiError(err, failure));
      return false;
    } finally {
      setIsBusy(false);
    }
  };

  const formProps = { submit, isBusy, invalid: (message: string) => notify('error', message) };

  const tabs: Array<{ id: Tab; label: string; icon: LucideIcon }> = [
    { id: 'list', label: `I Miei Calendari (${calendars.length})`, icon: CalIcon },
    { id: 'new', label: 'Nuovo Calendario', icon: Plus },
    { id: 'url', label: 'Google / Webcal URL', icon: Globe },
    { id: 'file', label: 'Carica .ICS', icon: Upload },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/70 backdrop-blur-md animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl bg-panel border border-border/80 rounded-2xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-border/60 flex items-center justify-between bg-panel-header/50">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
              <CalIcon size={18} />
            </div>
            <div>
              <h2 className="font-semibold text-base text-fg">Gestisci Calendari</h2>
              <p className="text-xs text-fg-muted">Configura i tuoi calendari locali, feed remoti o importa file .ics</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 text-fg-muted hover:text-fg hover:bg-panel-hover rounded-lg transition" title="Chiudi">
            <X size={18} />
          </button>
        </div>

        <div className="flex border-b border-border/60 bg-panel-header/20 px-3 pt-2 gap-1 overflow-x-auto shrink-0">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`px-3 py-2 text-xs font-medium rounded-t-xl border-b-2 transition cursor-pointer flex items-center gap-1.5 ${
                activeTab === id ? 'border-accent text-accent bg-panel' : 'border-transparent text-fg-muted hover:text-fg'
              }`}
            >
              <Icon size={14} />
              <span>{label}</span>
            </button>
          ))}
        </div>

        {feedback && (
          <div
            className={`px-5 py-2.5 border-b text-xs flex items-center justify-between ${
              feedback.type === 'success'
                ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-400'
                : 'bg-rose-500/10 border-rose-500/25 text-rose-400'
            }`}
          >
            <span>{feedback.text}</span>
            <button onClick={clear} className="text-fg-muted hover:text-fg">
              ✕
            </button>
          </div>
        )}

        <div className="p-5 overflow-y-auto flex-1 space-y-4">
          {activeTab === 'list' && <CalendarListTab calendars={calendars} notify={notify} onChanged={onCalendarsUpdated} />}
          {activeTab === 'new' && <NewCalendarForm {...formProps} />}
          {activeTab === 'url' && <ImportUrlForm {...formProps} />}
          {activeTab === 'file' && <ImportFileForm {...formProps} calendars={calendars} />}
        </div>

        <div className="px-5 py-3 border-t border-border/60 flex items-center justify-end bg-panel-header/30">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 bg-panel-hover text-fg rounded-xl text-xs font-medium hover:bg-panel transition cursor-pointer"
          >
            Chiudi
          </button>
        </div>
      </div>
    </div>
  );
};
