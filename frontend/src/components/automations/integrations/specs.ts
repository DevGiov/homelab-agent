import { Mail, Server, Zap, type LucideIcon } from 'lucide-react';

export interface FieldSpec {
  key: string;
  /** Dove finisce il valore nel payload: `config` in chiaro, `secrets` cifrato dal backend. */
  source: 'config' | 'secrets';
  kind: 'text' | 'number' | 'password' | 'checkbox';
  label: string;
  placeholder?: string;
  required?: boolean;
  defaultValue?: string | number | boolean;
  /** Colonne occupate su una griglia da 3 (default: riga intera). */
  cols?: 1 | 2 | 3;
}

export type FieldValues = Record<string, string | number | boolean>;

export interface IntegrationSpec {
  id: string;
  serviceType: string;
  name: (values: FieldValues) => string;
  fixedConfig?: Record<string, unknown>;
  title: string;
  subtitle: string;
  icon: LucideIcon;
  iconClass: string;
  statusLabels: { connected: string; other: string };
  testLabels: { success: string; failure: string };
  saveLabel: string;
  deleteTitle: string;
  fields: FieldSpec[];
}

export const INTEGRATION_SPECS: IntegrationSpec[] = [
  {
    id: 'email_primary',
    serviceType: 'email',
    name: (v) => `Email (${v.imap_user})`,
    title: 'Account Email (IMAP)',
    subtitle: 'Per briefing giornalieri, triage e generazione bozze',
    icon: Mail,
    iconClass: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
    statusLabels: { connected: 'Connesso', other: 'Da verificare' },
    testLabels: { success: 'Connessione Riuscita', failure: 'Errore Connessione' },
    saveLabel: 'Salva Credenziali',
    deleteTitle: 'Rimuovi account email',
    fields: [
      { key: 'imap_host', source: 'config', kind: 'text', label: 'Server IMAP', placeholder: 'imap.gmail.com o mail.homelab.local', required: true, cols: 2 },
      { key: 'imap_port', source: 'config', kind: 'number', label: 'Porta', required: true, defaultValue: 993, cols: 1 },
      { key: 'imap_user', source: 'config', kind: 'text', label: 'Indirizzo Email / Username', placeholder: 'utente@dominio.it', required: true },
      { key: 'imap_password', source: 'secrets', kind: 'password', label: 'Password o App Password', placeholder: 'Inserisci password o mantieni attuale' },
      { key: 'imap_use_ssl', source: 'config', kind: 'checkbox', label: 'Usa crittografia SSL/TLS (consigliato porta 993)', defaultValue: true },
    ],
  },
  {
    id: 'github_default',
    serviceType: 'github',
    name: () => 'GitHub Homelab Token',
    fixedConfig: { api_base: 'https://api.github.com' },
    title: 'GitHub Personal Access Token',
    subtitle: 'Per auto-repair loop, ispezione issue e notifiche',
    icon: Server,
    iconClass: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
    statusLabels: { connected: 'Attivo', other: 'Non verificato' },
    testLabels: { success: 'Autenticazione Riuscita', failure: 'Errore GitHub' },
    saveLabel: 'Salva Token',
    deleteTitle: 'Rimuovi token GitHub',
    fields: [
      { key: 'token', source: 'secrets', kind: 'password', label: 'Personal Access Token (classic o fine-grained)', placeholder: 'ghp_xxxxxxxxxxxxxxxxxxxx', required: true },
    ],
  },
  {
    id: 'homeassistant_default',
    serviceType: 'home_assistant',
    name: () => 'Home Assistant',
    title: 'Home Assistant',
    subtitle: 'Controllo entità domotiche, trigger e sensori homelab',
    icon: Zap,
    iconClass: 'bg-sky-500/15 text-sky-400 border-sky-500/30',
    statusLabels: { connected: 'Connesso', other: 'Non verificato' },
    testLabels: { success: 'Connessione Verificata', failure: 'Errore Home Assistant' },
    saveLabel: 'Salva Configurazione',
    deleteTitle: 'Rimuovi Home Assistant',
    fields: [
      { key: 'base_url', source: 'config', kind: 'text', label: 'URL Istanza Home Assistant', placeholder: 'http://192.168.1.69:8123', required: true, defaultValue: 'http://192.168.1.69:8123' },
      { key: 'access_token', source: 'secrets', kind: 'password', label: 'Long-Lived Access Token', placeholder: 'Bearer token generato dal profilo utente HA', required: true },
    ],
  },
];
