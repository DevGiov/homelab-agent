// Impostazioni modificabili dalla Web UI (backend: docs/settings/RUNTIME_SETTINGS_DESIGN.md, sezioni 4 e 5): canali e Telegram.
import { http } from './http';

/** Da dove viene il valore di un campo: `env` è il `.env`, `ui` un valore salvato dalla UI. */
export type SettingSource = 'env' | 'ui' | 'default';

export interface SettingField<T> {
  value: T;
  source: SettingSource;
}

/** Una credenziale non torna mai: solo se c'è e da dove viene. */
export interface SecretStatus {
  set: boolean;
  source: 'env' | 'ui' | null;
}

/** Livelli che un canale può ricevere senza conferma: `private` non si concede mai. */
export type ChannelClearance = 'public' | 'internal';

export interface TelegramStatus {
  /** Il ciclo di polling è attivo. */
  running: boolean;
  /** Ultimo errore della Bot API, già ripulito. */
  last_error: string | null;
  /** Messaggi scartati, per tipo. */
  ignored: Record<string, number>;
}

export interface TelegramSettings {
  enabled: SettingField<boolean>;
  allowed_users: SettingField<number[]>;
  clearance: SettingField<ChannelClearance>;
  secrets: { bot_token: SecretStatus };
  status: TelegramStatus;
}

export interface ChannelSettings {
  web_ui_url: SettingField<string>;
  reply_timeout_seconds: SettingField<number>;
  telegram: TelegramSettings;
  /** Falso senza `API_SECRET_KEY`: nessuna credenziale si può salvare dalla UI. */
  can_store_secrets: boolean;
}

/** `null` toglie il valore della UI: il campo (o la credenziale) torna al `.env`. */
export interface ChannelSettingsPatch {
  fields?: { web_ui_url?: string | null; reply_timeout_seconds?: number | null };
  telegram?: {
    fields?: { enabled?: boolean | null; allowed_users?: number[] | null; clearance?: ChannelClearance | null };
    secrets?: { bot_token?: string | null };
  };
  /** Per alzare il livello o aggiungere un utente: senza, il backend risponde 409 `confirm_required`. */
  confirm?: boolean;
}

export interface TelegramTestResult {
  ok: boolean;
  bot_username: string | null;
  error: string | null;
}

export function getChannelSettings(): Promise<ChannelSettings> {
  return http.get('/settings/channels');
}

export function patchChannelSettings(patch: ChannelSettingsPatch): Promise<ChannelSettings> {
  return http.patch('/settings/channels', patch);
}

/** Toglie ogni valore della UI dei canali: tutto torna al `.env`. */
export function resetChannelSettings(): Promise<ChannelSettings> {
  return http.post('/settings/channels/reset');
}

/** Prova il bot con il token salvato o, con `draftToken`, con quello della bozza senza salvarlo. */
export function testTelegramBot(draftToken?: string): Promise<TelegramTestResult> {
  return http.post('/settings/channels/telegram/test', draftToken ? { secrets: { bot_token: draftToken } } : undefined);
}
