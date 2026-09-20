import React, { useState, useEffect } from 'react';
import {
  Mail,
  Key,
  Shield,
  CheckCircle,
  AlertCircle,
  RefreshCw,
  Trash2,
  Lock,
  Server,
  Zap,
  Check,
} from 'lucide-react';
import {
  fetchIntegrations,
  saveIntegration,
  testIntegration,
  deleteIntegration,
  type ServiceIntegration,
  type IntegrationTestResult,
} from '../../api';

interface IntegrationsTabProps {
  onFeedback: (type: 'success' | 'error', text: string) => void;
}

export const IntegrationsTab: React.FC<IntegrationsTabProps> = ({ onFeedback }) => {
  const [integrations, setIntegrations] = useState<ServiceIntegration[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, IntegrationTestResult>>({});

  // Active edit state for email modal/form
  const [emailHost, setEmailHost] = useState<string>('');
  const [emailPort, setEmailPort] = useState<number>(993);
  const [emailUser, setEmailUser] = useState<string>('');
  const [emailPass, setEmailPass] = useState<string>('');
  const [emailSsl, setEmailSsl] = useState<boolean>(true);
  const [isSavingEmail, setIsSavingEmail] = useState<boolean>(false);

  // GitHub state
  const [githubToken, setGithubToken] = useState<string>('');
  const [isSavingGithub, setIsSavingGithub] = useState<boolean>(false);

  // Home Assistant state
  const [hassUrl, setHassUrl] = useState<string>('http://192.168.1.69:8123');
  const [hassToken, setHassToken] = useState<string>('');
  const [isSavingHass, setIsSavingHass] = useState<boolean>(false);

  const loadIntegrations = async () => {
    setIsLoading(true);
    try {
      const list = await fetchIntegrations();
      setIntegrations(list);

      // Pre-fill existing data
      const emailInt = list.find((i) => i.service_type === 'email');
      if (emailInt) {
        setEmailHost(emailInt.config?.imap_host || '');
        setEmailPort(Number(emailInt.config?.imap_port || 993));
        setEmailUser(emailInt.config?.imap_user || '');
        setEmailSsl(emailInt.config?.imap_use_ssl !== false);
        if (emailInt.secrets?.has_imap_password) {
          setEmailPass('••••••••');
        }
      }

      const ghInt = list.find((i) => i.service_type === 'github');
      if (ghInt && ghInt.secrets?.has_token) {
        setGithubToken('••••••••');
      }

      const haInt = list.find((i) => i.service_type === 'home_assistant');
      if (haInt) {
        setHassUrl(haInt.config?.base_url || 'http://192.168.1.69:8123');
        if (haInt.secrets?.has_access_token) {
          setHassToken('••••••••');
        }
      }
    } catch (err: any) {
      console.error('Errore caricamento integrazioni:', err);
      onFeedback('error', 'Impossibile caricare le integrazioni configurate.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadIntegrations();
  }, []);

  const handleSaveEmail = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!emailHost || !emailUser) {
      onFeedback('error', 'Host IMAP e Username sono obbligatori.');
      return;
    }
    setIsSavingEmail(true);
    try {
      const payload: Partial<ServiceIntegration> = {
        id: 'email_primary',
        service_type: 'email',
        name: `Email (${emailUser})`,
        config: {
          imap_host: emailHost.trim(),
          imap_port: emailPort,
          imap_user: emailUser.trim(),
          imap_use_ssl: emailSsl,
        },
        secrets: emailPass ? { imap_password: emailPass } : {},
      };
      await saveIntegration(payload);
      onFeedback('success', 'Credenziali Email salvate con successo!');
      await loadIntegrations();
    } catch (err: any) {
      onFeedback('error', `Errore salvataggio email: ${err?.response?.data?.detail || err.message}`);
    } finally {
      setIsSavingEmail(false);
    }
  };

  const handleSaveGithub = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!githubToken) {
      onFeedback('error', 'Inserisci un Personal Access Token GitHub.');
      return;
    }
    setIsSavingGithub(true);
    try {
      await saveIntegration({
        id: 'github_default',
        service_type: 'github',
        name: 'GitHub Homelab Token',
        config: { api_base: 'https://api.github.com' },
        secrets: { token: githubToken },
      });
      onFeedback('success', 'Token GitHub salvato con successo!');
      await loadIntegrations();
    } catch (err: any) {
      onFeedback('error', `Errore salvataggio GitHub: ${err?.response?.data?.detail || err.message}`);
    } finally {
      setIsSavingGithub(false);
    }
  };

  const handleSaveHass = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!hassUrl || !hassToken) {
      onFeedback('error', 'URL e Token di Home Assistant sono obbligatori.');
      return;
    }
    setIsSavingHass(true);
    try {
      await saveIntegration({
        id: 'homeassistant_default',
        service_type: 'home_assistant',
        name: 'Home Assistant',
        config: { base_url: hassUrl.trim() },
        secrets: { access_token: hassToken },
      });
      onFeedback('success', 'Integrazione Home Assistant salvata!');
      await loadIntegrations();
    } catch (err: any) {
      onFeedback('error', `Errore salvataggio Home Assistant: ${err?.response?.data?.detail || err.message}`);
    } finally {
      setIsSavingHass(false);
    }
  };

  const handleTest = async (id: string) => {
    setTestingId(id);
    try {
      const res = await testIntegration(id);
      setTestResults((prev) => ({ ...prev, [id]: res }));
      if (res.success) {
        onFeedback('success', res.message || 'Test di connessione superato con successo!');
      } else {
        onFeedback('error', res.error || 'Test di connessione fallito.');
      }
      await loadIntegrations();
    } catch (err: any) {
      onFeedback('error', `Errore durante il test: ${err?.response?.data?.detail || err.message}`);
    } finally {
      setTestingId(null);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm(`Sei sicuro di voler rimuovere l'integrazione "${id}"?`)) return;
    try {
      await deleteIntegration(id);
      onFeedback('success', `Integrazione "${id}" rimossa.`);
      await loadIntegrations();
    } catch (err: any) {
      onFeedback('error', `Errore eliminazione: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const emailIntegration = integrations.find((i) => i.service_type === 'email');
  const githubIntegration = integrations.find((i) => i.service_type === 'github');
  const hassIntegration = integrations.find((i) => i.service_type === 'home_assistant');

  return (
    <div className="space-y-6">
      {/* Header Info Banner */}
      <div className="p-4 rounded-2xl bg-panel border border-border/80 flex items-start justify-between gap-3 shadow-sm">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent shrink-0 mt-0.5">
            <Key size={18} />
          </div>
          <div>
            <h2 className="text-sm font-bold text-fg">Integrazioni & Credenziali Servizi</h2>
            <p className="text-xs text-fg-muted mt-0.5 leading-relaxed">
              Configura in sicurezza gli account esterni (posta IMAP per i briefing, GitHub per gli auto-repair, Home Assistant per la domotica).
              Le credenziali sensibili sono cifrate a riposo con crittografia simmetrica AES e non vengono mai esposte in chiaro.
            </p>
          </div>
        </div>

        <button
          onClick={loadIntegrations}
          disabled={isLoading}
          className="p-2 text-fg-muted hover:text-fg hover:bg-panel-header/60 rounded-xl border border-border transition cursor-pointer shrink-0"
          title="Ricarica integrazioni"
        >
          <RefreshCw size={15} className={isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Main Integrations Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* CARD 1: EMAIL (IMAP / SMTP) */}
        <div className="p-5 rounded-2xl bg-panel border border-border flex flex-col justify-between space-y-4 shadow-sm">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-border/60">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 flex items-center justify-center">
                  <Mail size={16} />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-fg">Account Email (IMAP)</h3>
                  <span className="text-[11px] text-fg-muted">Per briefing giornalieri, triage e generazione bozze</span>
                </div>
              </div>

              {emailIntegration && (
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-medium border flex items-center gap-1 ${
                    emailIntegration.status === 'connected'
                      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                      : 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                  }`}
                >
                  {emailIntegration.status === 'connected' ? <CheckCircle size={10} /> : <AlertCircle size={10} />}
                  {emailIntegration.status === 'connected' ? 'Connesso' : 'Da verificare'}
                </span>
              )}
            </div>

            <form onSubmit={handleSaveEmail} className="mt-4 space-y-3 text-xs">
              <div className="grid grid-cols-3 gap-2">
                <div className="col-span-2 space-y-1">
                  <label className="text-fg-muted block text-[11px] font-medium">Server IMAP</label>
                  <input
                    type="text"
                    placeholder="imap.gmail.com o mail.homelab.local"
                    value={emailHost}
                    onChange={(e) => setEmailHost(e.target.value)}
                    className="w-full px-2.5 py-1.5 rounded-lg bg-bg border border-border text-fg focus:outline-none focus:border-accent text-xs font-mono"
                    required
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-fg-muted block text-[11px] font-medium">Porta</label>
                  <input
                    type="number"
                    value={emailPort}
                    onChange={(e) => setEmailPort(Number(e.target.value))}
                    className="w-full px-2.5 py-1.5 rounded-lg bg-bg border border-border text-fg focus:outline-none focus:border-accent text-xs font-mono"
                    required
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-fg-muted block text-[11px] font-medium">Indirizzo Email / Username</label>
                <input
                  type="text"
                  placeholder="utente@dominio.it"
                  value={emailUser}
                  onChange={(e) => setEmailUser(e.target.value)}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-bg border border-border text-fg focus:outline-none focus:border-accent text-xs font-mono"
                  required
                />
              </div>

              <div className="space-y-1">
                <label className="text-fg-muted block text-[11px] font-medium flex items-center justify-between">
                  <span>Password o App Password</span>
                  <span className="text-[10px] text-accent flex items-center gap-1">
                    <Lock size={10} /> Cifrata AES
                  </span>
                </label>
                <input
                  type="password"
                  placeholder="Inserisci password o mantieni attuale"
                  value={emailPass}
                  onChange={(e) => setEmailPass(e.target.value)}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-bg border border-border text-fg focus:outline-none focus:border-accent text-xs font-mono"
                />
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="emailSslCheck"
                  checked={emailSsl}
                  onChange={(e) => setEmailSsl(e.target.checked)}
                  className="rounded border-border text-accent focus:ring-0 cursor-pointer"
                />
                <label htmlFor="emailSslCheck" className="text-fg-muted text-[11px] cursor-pointer">
                  Usa crittografia SSL/TLS (consigliato porta 993)
                </label>
              </div>

              {testResults['email_primary'] && (
                <div
                  className={`p-2.5 rounded-lg text-[11px] mt-2 border ${
                    testResults['email_primary'].success
                      ? 'bg-emerald-950/60 text-emerald-300 border-emerald-800'
                      : 'bg-rose-950/60 text-rose-300 border-rose-800'
                  }`}
                >
                  <p className="font-medium">
                    {testResults['email_primary'].success ? 'Connessione Riuscita' : 'Errore Connessione'}:
                  </p>
                  <p className="mt-0.5 text-[10.5px] opacity-90">
                    {testResults['email_primary'].message || testResults['email_primary'].error}
                  </p>
                </div>
              )}

              <div className="pt-2 flex items-center justify-between gap-2 border-t border-border/50">
                <div className="flex items-center gap-2">
                  <button
                    type="submit"
                    disabled={isSavingEmail}
                    className="px-3 py-1.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs font-medium transition shadow-sm cursor-pointer"
                  >
                    {isSavingEmail ? 'Salvataggio...' : 'Salva Credenziali'}
                  </button>

                  {emailIntegration && (
                    <button
                      type="button"
                      onClick={() => handleTest('email_primary')}
                      disabled={testingId === 'email_primary'}
                      className="px-3 py-1.5 bg-panel border border-border hover:border-accent/40 text-fg rounded-lg text-xs font-medium transition flex items-center gap-1.5 cursor-pointer"
                    >
                      <RefreshCw
                        size={12}
                        className={testingId === 'email_primary' ? 'animate-spin text-accent' : ''}
                      />
                      Testa Connessione
                    </button>
                  )}
                </div>

                {emailIntegration && (
                  <button
                    type="button"
                    onClick={() => handleDelete('email_primary')}
                    className="p-1.5 text-fg-muted hover:text-rose-400 rounded-lg transition"
                    title="Rimuovi account email"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </form>
          </div>
        </div>

        {/* CARD 2: GITHUB */}
        <div className="p-5 rounded-2xl bg-panel border border-border flex flex-col justify-between space-y-4 shadow-sm">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-border/60">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-purple-500/15 text-purple-400 border border-purple-500/30 flex items-center justify-center">
                  <Server size={16} />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-fg">GitHub Personal Access Token</h3>
                  <span className="text-[11px] text-fg-muted">Per auto-repair loop, ispezione issue e notifiche</span>
                </div>
              </div>

              {githubIntegration && (
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-medium border flex items-center gap-1 ${
                    githubIntegration.status === 'connected'
                      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                      : 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                  }`}
                >
                  {githubIntegration.status === 'connected' ? <CheckCircle size={10} /> : <AlertCircle size={10} />}
                  {githubIntegration.status === 'connected' ? 'Attivo' : 'Non verificato'}
                </span>
              )}
            </div>

            <form onSubmit={handleSaveGithub} className="mt-4 space-y-3 text-xs">
              <div className="space-y-1">
                <label className="text-fg-muted block text-[11px] font-medium flex items-center justify-between">
                  <span>Personal Access Token (classic o fine-grained)</span>
                  <span className="text-[10px] text-accent flex items-center gap-1">
                    <Lock size={10} /> Cifrato AES
                  </span>
                </label>
                <input
                  type="password"
                  placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
                  value={githubToken}
                  onChange={(e) => setGithubToken(e.target.value)}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-bg border border-border text-fg focus:outline-none focus:border-accent text-xs font-mono"
                  required
                />
              </div>

              {testResults['github_default'] && (
                <div
                  className={`p-2.5 rounded-lg text-[11px] mt-2 border ${
                    testResults['github_default'].success
                      ? 'bg-emerald-950/60 text-emerald-300 border-emerald-800'
                      : 'bg-rose-950/60 text-rose-300 border-rose-800'
                  }`}
                >
                  <p className="font-medium">
                    {testResults['github_default'].success ? 'Autenticazione Riuscita' : 'Errore GitHub'}:
                  </p>
                  <p className="mt-0.5 text-[10.5px] opacity-90">
                    {testResults['github_default'].message || testResults['github_default'].error}
                  </p>
                </div>
              )}

              <div className="pt-2 flex items-center justify-between gap-2 border-t border-border/50">
                <div className="flex items-center gap-2">
                  <button
                    type="submit"
                    disabled={isSavingGithub}
                    className="px-3 py-1.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs font-medium transition shadow-sm cursor-pointer"
                  >
                    {isSavingGithub ? 'Salvataggio...' : 'Salva Token'}
                  </button>

                  {githubIntegration && (
                    <button
                      type="button"
                      onClick={() => handleTest('github_default')}
                      disabled={testingId === 'github_default'}
                      className="px-3 py-1.5 bg-panel border border-border hover:border-accent/40 text-fg rounded-lg text-xs font-medium transition flex items-center gap-1.5 cursor-pointer"
                    >
                      <RefreshCw
                        size={12}
                        className={testingId === 'github_default' ? 'animate-spin text-accent' : ''}
                      />
                      Testa Connessione
                    </button>
                  )}
                </div>

                {githubIntegration && (
                  <button
                    type="button"
                    onClick={() => handleDelete('github_default')}
                    className="p-1.5 text-fg-muted hover:text-rose-400 rounded-lg transition"
                    title="Rimuovi token GitHub"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </form>
          </div>
        </div>

        {/* CARD 3: HOME ASSISTANT */}
        <div className="p-5 rounded-2xl bg-panel border border-border flex flex-col justify-between space-y-4 shadow-sm">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-border/60">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-sky-500/15 text-sky-400 border border-sky-500/30 flex items-center justify-center">
                  <Zap size={16} />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-fg">Home Assistant</h3>
                  <span className="text-[11px] text-fg-muted">Controllo entità domotiche, trigger e sensori homelab</span>
                </div>
              </div>

              {hassIntegration && (
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-medium border flex items-center gap-1 ${
                    hassIntegration.status === 'connected'
                      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                      : 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                  }`}
                >
                  {hassIntegration.status === 'connected' ? <CheckCircle size={10} /> : <AlertCircle size={10} />}
                  {hassIntegration.status === 'connected' ? 'Connesso' : 'Non verificato'}
                </span>
              )}
            </div>

            <form onSubmit={handleSaveHass} className="mt-4 space-y-3 text-xs">
              <div className="space-y-1">
                <label className="text-fg-muted block text-[11px] font-medium">URL Istanza Home Assistant</label>
                <input
                  type="text"
                  placeholder="http://192.168.1.69:8123"
                  value={hassUrl}
                  onChange={(e) => setHassUrl(e.target.value)}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-bg border border-border text-fg focus:outline-none focus:border-accent text-xs font-mono"
                  required
                />
              </div>

              <div className="space-y-1">
                <label className="text-fg-muted block text-[11px] font-medium flex items-center justify-between">
                  <span>Long-Lived Access Token</span>
                  <span className="text-[10px] text-accent flex items-center gap-1">
                    <Lock size={10} /> Cifrato AES
                  </span>
                </label>
                <input
                  type="password"
                  placeholder="Bearer token generato dal profilo utente HA"
                  value={hassToken}
                  onChange={(e) => setHassToken(e.target.value)}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-bg border border-border text-fg focus:outline-none focus:border-accent text-xs font-mono"
                  required
                />
              </div>

              {testResults['homeassistant_default'] && (
                <div
                  className={`p-2.5 rounded-lg text-[11px] mt-2 border ${
                    testResults['homeassistant_default'].success
                      ? 'bg-emerald-950/60 text-emerald-300 border-emerald-800'
                      : 'bg-rose-950/60 text-rose-300 border-rose-800'
                  }`}
                >
                  <p className="font-medium">
                    {testResults['homeassistant_default'].success ? 'Connessione Verificata' : 'Errore Home Assistant'}:
                  </p>
                  <p className="mt-0.5 text-[10.5px] opacity-90">
                    {testResults['homeassistant_default'].message || testResults['homeassistant_default'].error}
                  </p>
                </div>
              )}

              <div className="pt-2 flex items-center justify-between gap-2 border-t border-border/50">
                <div className="flex items-center gap-2">
                  <button
                    type="submit"
                    disabled={isSavingHass}
                    className="px-3 py-1.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs font-medium transition shadow-sm cursor-pointer"
                  >
                    {isSavingHass ? 'Salvataggio...' : 'Salva Configurazione'}
                  </button>

                  {hassIntegration && (
                    <button
                      type="button"
                      onClick={() => handleTest('homeassistant_default')}
                      disabled={testingId === 'homeassistant_default'}
                      className="px-3 py-1.5 bg-panel border border-border hover:border-accent/40 text-fg rounded-lg text-xs font-medium transition flex items-center gap-1.5 cursor-pointer"
                    >
                      <RefreshCw
                        size={12}
                        className={testingId === 'homeassistant_default' ? 'animate-spin text-accent' : ''}
                      />
                      Testa Connessione
                    </button>
                  )}
                </div>

                {hassIntegration && (
                  <button
                    type="button"
                    onClick={() => handleDelete('homeassistant_default')}
                    className="p-1.5 text-fg-muted hover:text-rose-400 rounded-lg transition"
                    title="Rimuovi Home Assistant"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </form>
          </div>
        </div>

        {/* CARD 4: SICUREZZA & ZERO AUTO-SEND */}
        <div className="p-5 rounded-2xl bg-panel border border-border flex flex-col justify-between space-y-4 shadow-sm">
          <div className="space-y-3">
            <div className="flex items-center gap-2.5 pb-3 border-b border-border/60">
              <div className="w-8 h-8 rounded-lg bg-amber-500/15 text-amber-400 border border-amber-500/30 flex items-center justify-center">
                <Shield size={16} />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-fg">Policy di Sicurezza e Zero Auto-Send</h3>
                <span className="text-[11px] text-fg-muted">Garanzie operative del runtime Homelab</span>
              </div>
            </div>

            <ul className="space-y-2 text-xs text-fg-muted">
              <li className="flex items-start gap-2">
                <Check size={14} className="text-emerald-400 shrink-0 mt-0.5" />
                <span>
                  <strong>Nessun Invio Automatico</strong>: l'agente può leggere le email e creare bozze di risposta (Draft), ma non invierà mai email senza autorizzazione esplicita.
                </span>
              </li>
              <li className="flex items-start gap-2">
                <Check size={14} className="text-emerald-400 shrink-0 mt-0.5" />
                <span>
                  <strong>Cifratura AES a Riposo</strong>: tutte le password e token sono memorizzati cifrati con Fernet AES nel database dedicato delle automazioni.
                </span>
              </li>
              <li className="flex items-start gap-2">
                <Check size={14} className="text-emerald-400 shrink-0 mt-0.5" />
                <span>
                  <strong>Scoped Secret Whitelist</strong>: ogni workflow accede unicamente ai secret esplicitamente dichiarati nella propria permission policy.
                </span>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
};
