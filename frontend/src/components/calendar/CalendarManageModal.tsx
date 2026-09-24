import React, { useState } from 'react';
import {
  X,
  Plus,
  Trash2,
  Calendar as CalIcon,
  Globe,
  Upload,
  HelpCircle,
  Palette,
  ExternalLink,
  Edit2,
  Save,
} from 'lucide-react';
import type { CalendarItem } from '../../api/calendarApi';
import { calendarApi } from '../../api/calendarApi';

interface CalendarManageModalProps {
  isOpen: boolean;
  onClose: () => void;
  calendars: CalendarItem[];
  onCalendarsUpdated: () => void;
}

const PRESET_COLORS = [
  '#3b82f6', // Blue
  '#8b5cf6', // Violet
  '#10b981', // Emerald
  '#f59e0b', // Amber
  '#ef4444', // Red
  '#06b6d4', // Cyan
  '#ec4899', // Pink
  '#6366f1', // Indigo
];

export const CalendarManageModal: React.FC<CalendarManageModalProps> = ({
  isOpen,
  onClose,
  calendars,
  onCalendarsUpdated,
}) => {
  const [activeTab, setActiveTab] = useState<'list' | 'new' | 'url' | 'file'>('list');

  // Stato Nuovo Calendario
  const [newName, setNewName] = useState('');
  const [newColor, setNewColor] = useState('#3b82f6');
  const [newDescription, setNewDescription] = useState('');

  // Stato Import URL
  const [feedUrl, setFeedUrl] = useState('');
  const [feedName, setFeedName] = useState('');
  const [feedColor, setFeedColor] = useState('#4285f4');
  const [showGoogleHelp, setShowGoogleHelp] = useState(false);

  // Stato Import File
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileTargetCalId, setFileTargetCalId] = useState<string>('__new__');
  const [fileNewCalName, setFileNewCalName] = useState('');
  const [fileCalColor, setFileCalColor] = useState('#10b981');

  // Stato Modifica In-line Calendario
  const [editingCalId, setEditingCalId] = useState<string | null>(null);
  const [editingCalName, setEditingCalName] = useState('');
  const [editingCalColor, setEditingCalColor] = useState('');

  // Stato Operazioni
  const [isLoading, setIsLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  if (!isOpen) return null;

  const showMsg = (type: 'success' | 'error', text: string) => {
    setStatusMessage({ type, text });
    setTimeout(() => setStatusMessage(null), 5000);
  };

  // Creazione nuovo calendario locale
  const handleCreateNew = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) {
      showMsg('error', 'Specifica un nome per il calendario.');
      return;
    }

    setIsLoading(true);
    try {
      await calendarApi.createCalendar({
        name: newName.trim(),
        color: newColor,
        description: newDescription.trim(),
      });
      showMsg('success', `Calendario '${newName}' creato con successo!`);
      setNewName('');
      setNewDescription('');
      onCalendarsUpdated();
      setActiveTab('list');
    } catch (err: any) {
      showMsg('error', err.response?.data?.detail || err.message || 'Errore durante la creazione.');
    } finally {
      setIsLoading(false);
    }
  };

  // Sottoscrizione URL / Google Calendar
  const handleImportUrl = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!feedUrl.trim()) {
      showMsg('error', 'Inserisci l\'URL del feed iCal.');
      return;
    }

    setIsLoading(true);
    try {
      const res = await calendarApi.importIcsUrl({
        url: feedUrl.trim(),
        name: feedName.trim() || undefined,
        color: feedColor,
      });
      showMsg(
        'success',
        `Feed importato con successo! Sincronizzati ${res.synced_count || 0} eventi.`
      );
      setFeedUrl('');
      setFeedName('');
      onCalendarsUpdated();
      setActiveTab('list');
    } catch (err: any) {
      showMsg('error', err.response?.data?.detail || err.message || 'Errore durante l\'importazione del feed.');
    } finally {
      setIsLoading(false);
    }
  };

  // Upload File .ICS
  const handleImportFile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) {
      showMsg('error', 'Seleziona un file .ics da importare.');
      return;
    }

    setIsLoading(true);
    try {
      const isNew = fileTargetCalId === '__new__';
      const res = await calendarApi.importIcsFile(
        selectedFile,
        isNew ? undefined : fileTargetCalId,
        isNew ? (fileNewCalName.trim() || selectedFile.name.replace('.ics', '')) : undefined,
        fileCalColor
      );
      showMsg('success', `File importato! ${res.imported_count || 0} eventi aggiunti al calendario.`);
      setSelectedFile(null);
      setFileNewCalName('');
      onCalendarsUpdated();
      setActiveTab('list');
    } catch (err: any) {
      showMsg('error', err.response?.data?.detail || err.message || 'Errore durante l\'importazione del file.');
    } finally {
      setIsLoading(false);
    }
  };

  // Inizia modifica calendario
  const startEditing = (cal: CalendarItem) => {
    setEditingCalId(cal.id);
    setEditingCalName(cal.name);
    setEditingCalColor(cal.color || '#3b82f6');
  };

  // Salva modifica calendario
  const saveEditing = async (calId: string) => {
    if (!editingCalName.trim()) return;
    setIsLoading(true);
    try {
      await calendarApi.updateCalendar(calId, {
        name: editingCalName.trim(),
        color: editingCalColor,
      });
      setEditingCalId(null);
      showMsg('success', 'Calendario aggiornato con successo.');
      onCalendarsUpdated();
    } catch (err: any) {
      showMsg('error', err.response?.data?.detail || 'Errore salvataggio calendario.');
    } finally {
      setIsLoading(false);
    }
  };

  // Elimina calendario
  const handleDeleteCalendar = async (cal: CalendarItem) => {
    if (calendars.length <= 1) {
      showMsg('error', 'Non puoi eliminare l\'unico calendario rimasto nel sistema.');
      return;
    }

    const confirm = window.confirm(`Sei sicuro di voler eliminare il calendario '${cal.name}' e tutti i suoi eventi associati?`);
    if (!confirm) return;

    setIsLoading(true);
    try {
      await calendarApi.deleteCalendar(cal.id);
      showMsg('success', `Calendario '${cal.name}' eliminato.`);
      onCalendarsUpdated();
    } catch (err: any) {
      showMsg('error', err.response?.data?.detail || 'Errore eliminazione.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/70 backdrop-blur-md animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl bg-panel border border-border/80 rounded-2xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header Modale */}
        <div className="px-5 py-4 border-b border-border/60 flex items-center justify-between bg-panel-header/50">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
              <CalIcon size={18} />
            </div>
            <div>
              <h2 className="font-semibold text-base text-fg">Gestisci Calendari</h2>
              <p className="text-xs text-fg-muted">
                Configura i tuoi calendari locali, feed remoti o importa file .ics
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-fg-muted hover:text-fg hover:bg-panel-hover rounded-lg transition"
            title="Chiudi"
          >
            <X size={18} />
          </button>
        </div>

        {/* Navigation Tabs */}
        <div className="flex border-b border-border/60 bg-panel-header/20 px-3 pt-2 gap-1 overflow-x-auto shrink-0">
          <button
            onClick={() => setActiveTab('list')}
            className={`px-3 py-2 text-xs font-medium rounded-t-xl border-b-2 transition cursor-pointer flex items-center gap-1.5 ${
              activeTab === 'list'
                ? 'border-accent text-accent bg-panel'
                : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            <CalIcon size={14} />
            <span>I Miei Calendari ({calendars.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('new')}
            className={`px-3 py-2 text-xs font-medium rounded-t-xl border-b-2 transition cursor-pointer flex items-center gap-1.5 ${
              activeTab === 'new'
                ? 'border-accent text-accent bg-panel'
                : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            <Plus size={14} />
            <span>Nuovo Calendario</span>
          </button>

          <button
            onClick={() => setActiveTab('url')}
            className={`px-3 py-2 text-xs font-medium rounded-t-xl border-b-2 transition cursor-pointer flex items-center gap-1.5 ${
              activeTab === 'url'
                ? 'border-accent text-accent bg-panel'
                : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            <Globe size={14} />
            <span>Google / Webcal URL</span>
          </button>

          <button
            onClick={() => setActiveTab('file')}
            className={`px-3 py-2 text-xs font-medium rounded-t-xl border-b-2 transition cursor-pointer flex items-center gap-1.5 ${
              activeTab === 'file'
                ? 'border-accent text-accent bg-panel'
                : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            <Upload size={14} />
            <span>Carica .ICS</span>
          </button>
        </div>

        {/* Alert messaggi */}
        {statusMessage && (
          <div
            className={`px-5 py-2.5 border-b text-xs flex items-center justify-between ${
              statusMessage.type === 'success'
                ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-400'
                : 'bg-rose-500/10 border-rose-500/25 text-rose-400'
            }`}
          >
            <span>{statusMessage.text}</span>
            <button onClick={() => setStatusMessage(null)} className="text-fg-muted hover:text-fg">
              ✕
            </button>
          </div>
        )}

        {/* Tab Content Area */}
        <div className="p-5 overflow-y-auto flex-1 space-y-4">
          {/* TAB 1: LISTA CALENDARI */}
          {activeTab === 'list' && (
            <div className="space-y-3">
              <p className="text-xs text-fg-muted">
                Gestisci i calendari registrati. Puoi rinominarli, cambiare il colore di visualizzazione o eliminarli.
              </p>

              <div className="divide-y divide-border/50 border border-border/70 rounded-xl overflow-hidden bg-panel-header/20">
                {calendars.map(cal => {
                  const isEditing = editingCalId === cal.id;

                  return (
                    <div
                      key={cal.id}
                      className="p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:bg-panel-hover/30 transition"
                    >
                      <div className="flex items-center gap-3 min-w-0 flex-1">
                        {isEditing ? (
                          <div className="flex items-center gap-2">
                            <input
                              type="color"
                              value={editingCalColor}
                              onChange={e => setEditingCalColor(e.target.value)}
                              className="w-7 h-7 rounded border border-border cursor-pointer bg-transparent"
                            />
                            <input
                              type="text"
                              value={editingCalName}
                              onChange={e => setEditingCalName(e.target.value)}
                              className="px-2.5 py-1 text-xs bg-input-bg text-fg border border-input-border rounded-lg focus:outline-none focus:border-accent"
                            />
                          </div>
                        ) : (
                          <>
                            <span
                              className="w-3.5 h-3.5 rounded-full shrink-0 shadow-sm"
                              style={{ backgroundColor: cal.color || '#3b82f6' }}
                            />
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="font-semibold text-xs text-fg truncate">
                                  {cal.name}
                                </span>
                                <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-panel border border-border text-fg-muted">
                                  {cal.source}
                                </span>
                              </div>
                              <p className="text-[11px] text-fg-muted truncate">
                                {cal.sync_url ? `Feed: ${cal.sync_url}` : 'Calendario locale'}
                              </p>
                            </div>
                          </>
                        )}
                      </div>

                      {/* Info & Azioni */}
                      <div className="flex items-center justify-end gap-2 shrink-0">
                        {cal.event_count !== undefined && (
                          <span className="text-xs text-fg-muted bg-panel px-2 py-1 rounded-lg border border-border/60">
                            {cal.event_count} eventi
                          </span>
                        )}

                        {isEditing ? (
                          <button
                            onClick={() => saveEditing(cal.id)}
                            disabled={isLoading}
                            className="p-1.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs flex items-center gap-1 transition cursor-pointer"
                            title="Salva modifiche"
                          >
                            <Save size={14} />
                            <span className="text-xs">Salva</span>
                          </button>
                        ) : (
                          <button
                            onClick={() => startEditing(cal)}
                            className="p-1.5 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition"
                            title="Modifica nome e colore"
                          >
                            <Edit2 size={14} />
                          </button>
                        )}

                        <button
                          onClick={() => handleDeleteCalendar(cal)}
                          disabled={calendars.length <= 1 || isLoading}
                          className="p-1.5 text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 rounded-lg transition disabled:opacity-30 disabled:cursor-not-allowed"
                          title={calendars.length <= 1 ? 'Impossibile eliminare l\'unico calendario' : 'Elimina calendario'}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* TAB 2: NUOVO CALENDARIO LOCALE */}
          {activeTab === 'new' && (
            <form onSubmit={handleCreateNew} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-fg/90 mb-1.5">
                  Nome Calendario <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  placeholder="es. Lavoro, Palestra, Manutenzione Homelab..."
                  required
                  className="w-full px-3.5 py-2.5 bg-input-bg text-fg border border-input-border rounded-xl text-xs placeholder:text-fg-muted/70 focus:outline-none focus:border-accent"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-fg/90 mb-1.5 flex items-center gap-1">
                  <Palette size={13} /> Colore Calendario
                </label>
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  {PRESET_COLORS.map(c => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setNewColor(c)}
                      className={`w-7 h-7 rounded-full transition transform cursor-pointer border ${
                        newColor.toLowerCase() === c.toLowerCase()
                          ? 'scale-110 border-white ring-2 ring-accent shadow-md'
                          : 'border-transparent hover:scale-105'
                      }`}
                      style={{ backgroundColor: c }}
                    />
                  ))}
                  <input
                    type="color"
                    value={newColor}
                    onChange={e => setNewColor(e.target.value)}
                    className="w-8 h-8 rounded-full border border-border cursor-pointer bg-transparent"
                    title="Colore personalizzato"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-fg/90 mb-1.5">
                  Descrizione (opzionale)
                </label>
                <input
                  type="text"
                  value={newDescription}
                  onChange={e => setNewDescription(e.target.value)}
                  placeholder="Note o dettagli sullo scopo del calendario..."
                  className="w-full px-3.5 py-2 bg-input-bg text-fg border border-input-border rounded-xl text-xs placeholder:text-fg-muted/70 focus:outline-none focus:border-accent"
                />
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  type="submit"
                  disabled={isLoading}
                  className="px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-medium flex items-center gap-1.5 shadow-sm shadow-accent/25 transition cursor-pointer"
                >
                  <Plus size={14} />
                  <span>{isLoading ? 'Creazione...' : 'Crea Calendario'}</span>
                </button>
              </div>
            </form>
          )}

          {/* TAB 3: IMPORTA GOOGLE CALENDAR / WEBCAL */}
          {activeTab === 'url' && (
            <form onSubmit={handleImportUrl} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-fg/90 mb-1.5">
                  URL Feed iCalendar (Google Calendar o Webcal) <span className="text-rose-400">*</span>
                </label>
                <input
                  type="url"
                  value={feedUrl}
                  onChange={e => {
                    setFeedUrl(e.target.value);
                    if (!feedName && e.target.value.includes('google.com')) {
                      setFeedName('Google Calendar');
                    }
                  }}
                  placeholder="https://calendar.google.com/calendar/ical/.../basic.ics oppure webcal://..."
                  required
                  className="w-full px-3.5 py-2.5 bg-input-bg text-fg border border-input-border rounded-xl text-xs placeholder:text-fg-muted/70 focus:outline-none focus:border-accent font-mono"
                />
              </div>

              {/* Guida Google Calendar */}
              <div className="p-3 bg-panel-header/40 border border-border/60 rounded-xl space-y-2 text-xs">
                <button
                  type="button"
                  onClick={() => setShowGoogleHelp(!showGoogleHelp)}
                  className="flex items-center justify-between w-full font-medium text-accent hover:underline text-left cursor-pointer"
                >
                  <span className="flex items-center gap-1.5">
                    <HelpCircle size={14} /> Come ottenere il link segreto da Google Calendar
                  </span>
                  <span>{showGoogleHelp ? '▲' : '▼'}</span>
                </button>

                {showGoogleHelp && (
                  <ol className="list-decimal pl-5 space-y-1 text-fg-muted text-[11px] leading-relaxed pt-1">
                    <li>Apri Google Calendar da browser (<a href="https://calendar.google.com" target="_blank" rel="noreferrer" className="text-accent underline inline-flex items-center gap-0.5">calendar.google.com <ExternalLink size={10} /></a>).</li>
                    <li>Sulla sinistra, sotto <strong>I miei calendari</strong>, passa con il mouse sul tuo calendario e clicca sui <strong>tre puntini (Opzioni)</strong> → <strong>Impostazioni e condivisione</strong>.</li>
                    <li>Scorri in basso fino alla sezione <strong>Integra calendario</strong>.</li>
                    <li>Individua e copia la voce <strong>"Indirizzo segreto in formato iCal"</strong> (attenzione: non usare quello pubblico se il calendario è privato).</li>
                    <li>Incolla l'indirizzo nel campo sopra e clicca <strong>Importa Feed</strong>.</li>
                  </ol>
                )}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-fg/90 mb-1.5">
                    Nome Assegnato
                  </label>
                  <input
                    type="text"
                    value={feedName}
                    onChange={e => setFeedName(e.target.value)}
                    placeholder="es. Google Personale"
                    className="w-full px-3.5 py-2 bg-input-bg text-fg border border-input-border rounded-xl text-xs placeholder:text-fg-muted/70 focus:outline-none focus:border-accent"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-fg/90 mb-1.5">
                    Colore
                  </label>
                  <div className="flex items-center gap-2 pt-0.5">
                    {PRESET_COLORS.slice(0, 5).map(c => (
                      <button
                        key={c}
                        type="button"
                        onClick={() => setFeedColor(c)}
                        className={`w-6 h-6 rounded-full border transition cursor-pointer ${
                          feedColor === c ? 'scale-110 border-white ring-2 ring-accent' : 'border-transparent'
                        }`}
                        style={{ backgroundColor: c }}
                      />
                    ))}
                    <input
                      type="color"
                      value={feedColor}
                      onChange={e => setFeedColor(e.target.value)}
                      className="w-7 h-7 rounded border border-border cursor-pointer bg-transparent"
                    />
                  </div>
                </div>
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  type="submit"
                  disabled={isLoading}
                  className="px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-medium flex items-center gap-1.5 shadow-sm shadow-accent/25 transition cursor-pointer"
                >
                  <Globe size={14} />
                  <span>{isLoading ? 'Sottoscrizione in corso...' : 'Sottoscrivi e Sincronizza'}</span>
                </button>
              </div>
            </form>
          )}

          {/* TAB 4: CARICA FILE .ICS */}
          {activeTab === 'file' && (
            <form onSubmit={handleImportFile} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-fg/90 mb-1.5">
                  Seleziona file .ICS esportato da Google Calendar, Outlook o Apple Calendar
                </label>
                <div className="border-2 border-dashed border-border/80 hover:border-accent/60 rounded-xl p-5 text-center bg-input-bg transition cursor-pointer flex flex-col items-center justify-center gap-2">
                  <Upload size={24} className="text-accent" />
                  <input
                    type="file"
                    accept=".ics,text/calendar"
                    onChange={e => {
                      if (e.target.files?.[0]) {
                        setSelectedFile(e.target.files[0]);
                        if (!fileNewCalName) {
                          setFileNewCalName(e.target.files[0].name.replace('.ics', ''));
                        }
                      }
                    }}
                    className="text-xs text-fg file:mr-4 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-medium file:bg-accent file:text-white hover:file:bg-accent-hover cursor-pointer"
                  />
                  {selectedFile && (
                    <p className="text-xs text-emerald-400 font-medium">
                      File selezionato: {selectedFile.name} ({(selectedFile.size / 1024).toFixed(1)} KB)
                    </p>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-fg/90 mb-1.5">
                    Destinazione Eventi
                  </label>
                  <select
                    value={fileTargetCalId}
                    onChange={e => setFileTargetCalId(e.target.value)}
                    className="w-full px-3 py-2 bg-input-bg text-fg border border-input-border rounded-xl text-xs focus:outline-none focus:border-accent"
                  >
                    <option value="__new__" className="bg-panel text-fg">+ Crea un nuovo calendario per questo file</option>
                    {calendars.map(c => (
                      <option key={c.id} value={c.id} className="bg-panel text-fg">
                        Importa dentro: {c.name}
                      </option>
                    ))}
                  </select>
                </div>

                {fileTargetCalId === '__new__' && (
                  <div className="space-y-3 sm:col-span-2">
                    <div>
                      <label className="block text-xs font-medium text-fg/90 mb-1.5">
                        Nome Nuovo Calendario
                      </label>
                      <input
                        type="text"
                        value={fileNewCalName}
                        onChange={e => setFileNewCalName(e.target.value)}
                        placeholder="es. Eventi Importati"
                        className="w-full px-3.5 py-2 bg-input-bg text-fg border border-input-border rounded-xl text-xs placeholder:text-fg-muted/70 focus:outline-none focus:border-accent"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-fg/90 mb-1.5">
                        Colore Calendario
                      </label>
                      <div className="flex items-center gap-2 flex-wrap">
                        {PRESET_COLORS.map(c => (
                          <button
                            key={c}
                            type="button"
                            onClick={() => setFileCalColor(c)}
                            className={`w-6 h-6 rounded-full border transition cursor-pointer ${
                              fileCalColor === c ? 'scale-110 border-white ring-2 ring-accent' : 'border-transparent'
                            }`}
                            style={{ backgroundColor: c }}
                          />
                        ))}
                        <input
                          type="color"
                          value={fileCalColor}
                          onChange={e => setFileCalColor(e.target.value)}
                          className="w-7 h-7 rounded border border-border cursor-pointer bg-transparent"
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  type="submit"
                  disabled={!selectedFile || isLoading}
                  className="px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-medium flex items-center gap-1.5 shadow-sm shadow-accent/25 transition cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <Upload size={14} />
                  <span>{isLoading ? 'Importazione in corso...' : 'Importa File .ICS'}</span>
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Footer */}
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
