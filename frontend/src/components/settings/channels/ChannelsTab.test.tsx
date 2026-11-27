import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChannelSettings, TelegramTestResult } from '../../../api/settings';
import { ApiError } from '../../../api/http';
import { jsonResponse, mockBackend, type RecordedRequest } from '../../../test/backend';
import { SETTINGS_ERROR_MESSAGES, settingsErrorMessage } from '../../../utils/settingsErrors';
import { ChannelsTab } from './ChannelsTab';

const base: ChannelSettings = {
  web_ui_url: { value: 'https://agente.example', source: 'env' },
  reply_timeout_seconds: { value: 300, source: 'default' },
  telegram: {
    enabled: { value: true, source: 'default' },
    allowed_users: { value: [111, 222], source: 'env' },
    clearance: { value: 'public', source: 'default' },
    secrets: { bot_token: { set: true, source: 'env' } },
    status: { running: true, last_error: null, ignored: {} },
  },
  can_store_secrets: true,
};

/** Una copia di `base` con le modifiche date (un livello di profondità per la sezione `telegram`). */
function variant(change: Partial<Omit<ChannelSettings, 'telegram'>> & { telegram?: Partial<ChannelSettings['telegram']> }): ChannelSettings {
  return { ...base, ...change, telegram: { ...base.telegram, ...change.telegram } };
}

interface Options {
  settings?: ChannelSettings;
  patch?: (req: RecordedRequest) => Response;
  test?: (req: RecordedRequest) => Response;
  reset?: (req: RecordedRequest) => Response;
}

function setup({ settings = base, patch, test, reset }: Options = {}) {
  const backend = mockBackend({
    'GET /v1/settings/channels': () => jsonResponse(settings),
    'PATCH /v1/settings/channels': patch ?? (() => jsonResponse(settings)),
    'POST /v1/settings/channels/reset': reset ?? (() => jsonResponse(settings)),
    'POST /v1/settings/channels/telegram/test':
      test ?? (() => jsonResponse({ ok: true, bot_username: 'agente_bot', error: null } satisfies TelegramTestResult)),
  });
  render(<ChannelsTab />);
  return backend;
}

const telegram = () => within(screen.getByTestId('channels-telegram'));
const general = () => within(screen.getByTestId('channels-general'));
const sent = (requests: RecordedRequest[], method: string, path: string) => requests.filter((r) => r.method === method && r.path === path);
const patches = (requests: RecordedRequest[]) => sent(requests, 'PATCH', '/v1/settings/channels');
const ready = () => screen.findByTestId('channels-telegram');

const conflict = (code: string, message = 'testo del backend') => jsonResponse({ detail: { code, message } }, 409);

function addUser(id: string) {
  fireEvent.change(screen.getByLabelText('Id Telegram da aggiungere'), { target: { value: id } });
  fireEvent.click(screen.getByRole('button', { name: /aggiungi/ }));
}

beforeEach(() => {
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});
afterEach(cleanup);

describe('scheda Canali: valori e origini', () => {
  it('mostra i valori con l\'origine di ognuno', async () => {
    setup();
    await ready();
    expect((telegram().getByLabelText(/^Dati che può ricevere/) as HTMLSelectElement).value).toBe('public');
    expect(screen.getByTestId('origin-enabled').textContent).toBe('(predefinito)');
    expect(screen.getByTestId('origin-allowed_users').textContent).toBe('(da .env)');
    expect(screen.getByTestId('origin-clearance').textContent).toBe('(predefinito)');
    expect(screen.getByTestId('origin-web_ui_url').textContent).toBe('(da .env)');
    expect(screen.getByTestId('origin-reply_timeout_seconds').textContent).toBe('(predefinito)');
    expect((general().getByLabelText('Indirizzo della Web UI') as HTMLInputElement).value).toBe('https://agente.example');
    expect((general().getByLabelText(/^Attesa massima/) as HTMLInputElement).value).toBe('300');
    const list = telegram().getByRole('list', { name: 'Utenti ammessi' });
    expect(within(list).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['111', '222']);
    expect(screen.getByRole('checkbox', { name: 'Telegram attivo' })).toBeTruthy();
    expect((screen.getByRole('checkbox', { name: 'Telegram attivo' }) as HTMLInputElement).checked).toBe(true);
  });

  it('il pulsante «torna al .env» c\'è solo per i campi che vengono dalla UI e manda null', async () => {
    const { requests } = setup({ settings: variant({ web_ui_url: { value: 'https://altro.example', source: 'ui' } }) });
    await ready();
    expect(screen.queryByRole('button', { name: /Riporta «Utenti ammessi»/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Riporta «Attesa massima/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Riporta «Indirizzo della Web UI» al .env' }));
    await waitFor(() => expect(patches(requests)).toHaveLength(1));
    expect(patches(requests)[0].body).toEqual({ fields: { web_ui_url: null } });
  });

  it('mostra la guida con BotFather e @userinfobot', async () => {
    setup();
    await ready();
    const help = telegram().getByText('Come si configura').closest('details')!;
    expect(help.textContent).toContain('@BotFather');
    expect(help.textContent).toContain('/newbot');
    expect(help.textContent).toContain('@userinfobot');
  });
});

describe('scheda Canali: stato di Telegram', () => {
  const status = () => screen.getByTestId('telegram-status').textContent;
  const stopped = { running: false, last_error: null, ignored: {} };

  it('attivo quando il canale gira', async () => {
    setup();
    await ready();
    expect(status()).toBe('attivo');
  });

  it('fermo: manca il token', async () => {
    setup({ settings: variant({ telegram: { secrets: { bot_token: { set: false, source: null } }, status: stopped } }) });
    await ready();
    expect(status()).toBe('fermo: manca il token');
  });

  it('fermo: disattivato', async () => {
    setup({ settings: variant({ telegram: { enabled: { value: false, source: 'ui' }, status: stopped } }) });
    await ready();
    expect(status()).toBe('fermo: disattivato');
  });

  it('fermo: nessun utente ammesso', async () => {
    setup({ settings: variant({ telegram: { allowed_users: { value: [], source: 'ui' }, status: stopped } }) });
    await ready();
    expect(status()).toBe('fermo: nessun utente ammesso');
    expect(telegram().getByText('Nessun utente ammesso: il canale resta fermo.')).toBeTruthy();
  });

  it('mostra l\'ultimo errore e i messaggi scartati', async () => {
    setup({ settings: variant({ telegram: { status: { running: false, last_error: 'Unauthorized', ignored: { photo: 2, sticker: 1 } } } }) });
    await ready();
    expect(screen.getByTestId('telegram-last-error').textContent).toBe('Ultimo errore: Unauthorized');
    expect(telegram().getByText(/Messaggi scartati.*: 3\./)).toBeTruthy();
  });

  it('l\'interruttore salva subito e manda solo enabled', async () => {
    const { requests } = setup();
    await ready();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Telegram attivo' }));
    await waitFor(() => expect(patches(requests)).toHaveLength(1));
    expect(patches(requests)[0].body).toEqual({ telegram: { fields: { enabled: false } } });
  });
});

describe('scheda Canali: salvataggio', () => {
  it('manda solo i campi cambiati (generale)', async () => {
    const { requests } = setup();
    await ready();
    const save = screen.getByRole('button', { name: 'Salva le impostazioni generali' }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(general().getByLabelText(/^Attesa massima/), { target: { value: '600' } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    await waitFor(() => expect(patches(requests)).toHaveLength(1));
    expect(patches(requests)[0].body).toEqual({ fields: { reply_timeout_seconds: 600 } });
    expect(await screen.findByText('Impostazioni generali salvate.')).toBeTruthy();
  });

  it('un indirizzo vuoto si manda come stringa vuota, non come null', async () => {
    const { requests } = setup();
    await ready();
    fireEvent.change(general().getByLabelText('Indirizzo della Web UI'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salva le impostazioni generali' }));
    await waitFor(() => expect(patches(requests)).toHaveLength(1));
    expect(patches(requests)[0].body).toEqual({ fields: { web_ui_url: '' } });
  });

  it('valida attesa e indirizzo prima di inviare', async () => {
    const { requests } = setup();
    await ready();
    const save = screen.getByRole('button', { name: 'Salva le impostazioni generali' }) as HTMLButtonElement;
    for (const bad of ['29', '3601', '12.5', '']) {
      fireEvent.change(general().getByLabelText(/^Attesa massima/), { target: { value: bad } });
      expect(save.disabled).toBe(true);
      expect(general().getByRole('alert')).toBeTruthy();
    }
    fireEvent.change(general().getByLabelText(/^Attesa massima/), { target: { value: '300' } });
    fireEvent.change(general().getByLabelText('Indirizzo della Web UI'), { target: { value: 'ftp://x.example' } });
    expect(save.disabled).toBe(true);
    expect(general().getByRole('alert').textContent).toContain('http://');
    expect(patches(requests)).toHaveLength(0);
  });

  it('manda solo i campi cambiati (Telegram): il livello, senza utenti né token', async () => {
    const { requests } = setup();
    await ready();
    fireEvent.change(telegram().getByLabelText(/^Dati che può ricevere/), { target: { value: 'public' } });
    expect((screen.getByRole('button', { name: 'Salva Telegram' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(telegram().getByLabelText(/^Dati che può ricevere/), { target: { value: 'internal' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salva Telegram' }));
    await waitFor(() => expect(patches(requests)).toHaveLength(1));
    expect(patches(requests)[0].body).toEqual({ telegram: { fields: { clearance: 'internal' } } });
  });

  it('togliere un utente manda la lista nuova', async () => {
    const { requests } = setup();
    await ready();
    fireEvent.click(screen.getByRole('button', { name: "Togli l'utente 111" }));
    fireEvent.click(screen.getByRole('button', { name: 'Salva Telegram' }));
    await waitFor(() => expect(patches(requests)).toHaveLength(1));
    expect(patches(requests)[0].body).toEqual({ telegram: { fields: { allowed_users: [222] } } });
  });
});

describe('scheda Canali: utenti ammessi', () => {
  it('accetta solo interi positivi, senza doppioni', async () => {
    setup();
    await ready();
    for (const bad of ['abc', '-5', '0', '12.5', '99999999999999999999', '111']) {
      addUser(bad);
      expect(telegram().getByRole('alert')).toBeTruthy();
    }
    expect(within(telegram().getByRole('list', { name: 'Utenti ammessi' })).getAllByRole('listitem')).toHaveLength(2);
    addUser('333');
    expect(telegram().queryByRole('alert')).toBeNull();
    expect(within(telegram().getByRole('list', { name: 'Utenti ammessi' })).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['111', '222', '333']);
    expect((screen.getByLabelText('Id Telegram da aggiungere') as HTMLInputElement).value).toBe('');
  });

  it('Invio aggiunge l\'id', async () => {
    setup();
    await ready();
    const input = screen.getByLabelText('Id Telegram da aggiungere');
    fireEvent.change(input, { target: { value: '444' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(telegram().getByText('444')).toBeTruthy();
  });

  it('aggiungere un utente: 409 confirm_required, conferma, ripete con confirm true', async () => {
    const { requests } = setup({ patch: (req) => (req.body?.confirm ? jsonResponse(base) : conflict('confirm_required', "L'utente 333 potrà dare comandi all'agente.")) });
    await ready();
    addUser('333');
    fireEvent.click(screen.getByRole('button', { name: 'Salva Telegram' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog.textContent).toContain("L'utente 333 potrà dare comandi all'agente. Confermi?");
    expect(patches(requests)).toHaveLength(1);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Conferma' }));
    await waitFor(() => expect(patches(requests)).toHaveLength(2));
    const [first, second] = patches(requests);
    expect(first.body).toEqual({ telegram: { fields: { allowed_users: [111, 222, 333] } } });
    expect(second.body).toEqual({ ...first.body, confirm: true });
    expect(await screen.findByText('Telegram salvato.')).toBeTruthy();
  });

  it('senza testo dal backend la conferma nomina l\'utente aggiunto', async () => {
    setup({ patch: (req) => (req.body?.confirm ? jsonResponse(base) : jsonResponse({ detail: { code: 'confirm_required' } }, 409)) });
    await ready();
    addUser('333');
    fireEvent.click(screen.getByRole('button', { name: 'Salva Telegram' }));
    expect((await screen.findByRole('alertdialog')).textContent).toContain("L'utente 333 potrà dare comandi all'agente. Confermi?");
  });

  it('senza testo dal backend, alzare il livello dice che le risposte arrivano senza conferma', async () => {
    setup({ patch: (req) => (req.body?.confirm ? jsonResponse(base) : jsonResponse({ detail: { code: 'confirm_required' } }, 409)) });
    await ready();
    fireEvent.change(telegram().getByLabelText(/^Dati che può ricevere/), { target: { value: 'internal' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salva Telegram' }));
    expect((await screen.findByRole('alertdialog')).textContent).toContain('Le risposte fino a dati interni arriveranno su Telegram senza conferma. Confermi?');
  });

  it('annullare la conferma non ripete il PATCH, non dice «salvato» e tiene la bozza', async () => {
    const { requests } = setup({ patch: () => conflict('confirm_required') });
    await ready();
    addUser('333');
    fireEvent.click(screen.getByRole('button', { name: 'Salva Telegram' }));
    const dialog = await screen.findByRole('alertdialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Annulla' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(patches(requests)).toHaveLength(1);
    expect(screen.queryByText('Telegram salvato.')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(telegram().getByText('333')).toBeTruthy();
  });
});

describe('scheda Canali: token in sola scrittura', () => {
  const SECRET = '123456:ABC-secret-token-value';
  const tokenInput = () => screen.getByLabelText('Token del bot') as HTMLInputElement;

  it('mostra lo stato a parole e un campo password vuoto', async () => {
    setup();
    await ready();
    expect(screen.getByTestId('secret-bot_token').textContent).toBe('impostato (da .env)');
    expect(tokenInput().type).toBe('password');
    expect(tokenInput().value).toBe('');
    expect(screen.queryByRole('button', { name: /Togli il token/ })).toBeNull();
    cleanup();

    setup({ settings: variant({ telegram: { secrets: { bot_token: { set: true, source: 'ui' } } } }) });
    await ready();
    expect(screen.getByTestId('secret-bot_token').textContent).toBe('impostato dalla UI');
    cleanup();

    setup({ settings: variant({ telegram: { secrets: { bot_token: { set: false, source: null } } } }) });
    await ready();
    expect(screen.getByTestId('secret-bot_token').textContent).toBe('non impostato');
  });

  it('il token va nel PATCH e poi non resta né nel campo né nella pagina', async () => {
    const { requests } = setup({ settings: variant({ telegram: { secrets: { bot_token: { set: true, source: 'ui' } } } }) });
    await ready();
    fireEvent.change(tokenInput(), { target: { value: SECRET } });
    fireEvent.click(screen.getByRole('button', { name: 'Salva Telegram' }));
    await waitFor(() => expect(patches(requests)).toHaveLength(1));
    expect(patches(requests)[0].body).toEqual({ telegram: { secrets: { bot_token: SECRET } } });
    await screen.findByText('Telegram salvato.');
    expect(tokenInput().value).toBe('');
    expect(document.body.innerHTML).not.toContain(SECRET);
  });

  it('il token non resta nella pagina nemmeno se il salvataggio fallisce', async () => {
    setup({ patch: () => conflict('no_secret_key') });
    await ready();
    fireEvent.change(tokenInput(), { target: { value: SECRET } });
    fireEvent.click(screen.getByRole('button', { name: 'Salva Telegram' }));
    expect((await screen.findByRole('alert')).textContent).toBe(SETTINGS_ERROR_MESSAGES.no_secret_key);
    expect(tokenInput().value).toBe('');
    expect(document.body.innerHTML).not.toContain(SECRET);
  });

  it('«Togli» per un token della UI manda null', async () => {
    const { requests } = setup({ settings: variant({ telegram: { secrets: { bot_token: { set: true, source: 'ui' } } } }) });
    await ready();
    fireEvent.click(screen.getByRole('button', { name: 'Togli il token salvato dalla UI' }));
    await waitFor(() => expect(patches(requests)).toHaveLength(1));
    expect(patches(requests)[0].body).toEqual({ telegram: { secrets: { bot_token: null } } });
  });

  it('senza can_store_secrets il campo è disabilitato e dice perché', async () => {
    setup({ settings: variant({ can_store_secrets: false }) });
    await ready();
    expect(tokenInput().disabled).toBe(true);
    const reason = telegram().getByText(/imposta API_SECRET_KEY nel \.env e ricrea/);
    expect(tokenInput().getAttribute('aria-describedby')).toBe(reason.id);
  });
});

describe('scheda Canali: Prova il bot', () => {
  const SECRET = '999:draft-token-value';

  it('con un token scritto lo manda nella bozza, mostra @nome e svuota il campo', async () => {
    const { requests } = setup();
    await ready();
    fireEvent.change(screen.getByLabelText('Token del bot'), { target: { value: SECRET } });
    fireEvent.click(screen.getByRole('button', { name: 'Prova il bot' }));
    expect(await screen.findByText('Il bot risponde: @agente_bot.')).toBeTruthy();
    expect(screen.getByText('Il bot risponde: @agente_bot.').getAttribute('role')).toBe('status');
    const tests = sent(requests, 'POST', '/v1/settings/channels/telegram/test');
    expect(tests).toHaveLength(1);
    expect(tests[0].body).toEqual({ secrets: { bot_token: SECRET } });
    expect((screen.getByLabelText('Token del bot') as HTMLInputElement).value).toBe('');
    expect(document.body.innerHTML).not.toContain(SECRET);
    expect(patches(requests)).toHaveLength(0);
  });

  it('senza token scritto non manda nessun corpo: vale quello salvato', async () => {
    const { requests } = setup();
    await ready();
    fireEvent.click(screen.getByRole('button', { name: 'Prova il bot' }));
    await screen.findByText('Il bot risponde: @agente_bot.');
    expect(sent(requests, 'POST', '/v1/settings/channels/telegram/test')[0].body).toBeUndefined();
  });

  it('mostra l\'errore della prova', async () => {
    setup({ test: () => jsonResponse({ ok: false, bot_username: null, error: 'Unauthorized' }) });
    await ready();
    fireEvent.click(screen.getByRole('button', { name: 'Prova il bot' }));
    const result = await screen.findByText('Prova non riuscita: Unauthorized');
    expect(result.getAttribute('role')).toBe('status');
  });

  it('un errore HTTP della prova diventa un messaggio, senza il token', async () => {
    setup({ test: () => jsonResponse({ detail: 'Backend giù' }, 500) });
    await ready();
    fireEvent.change(screen.getByLabelText('Token del bot'), { target: { value: SECRET } });
    fireEvent.click(screen.getByRole('button', { name: 'Prova il bot' }));
    expect(await screen.findByText('Prova non riuscita: Backend giù')).toBeTruthy();
    expect(document.body.innerHTML).not.toContain(SECRET);
  });
});

describe('scheda Canali: ripristino', () => {
  it('«Ripristina il .env» chiede conferma e poi chiama il reset', async () => {
    const { requests } = setup();
    await ready();
    fireEvent.change(telegram().getByLabelText(/^Dati che può ricevere/), { target: { value: 'internal' } });
    fireEvent.click(screen.getByRole('button', { name: /Ripristina il \.env/ }));
    const dialog = await screen.findByRole('alertdialog');
    expect(sent(requests, 'POST', '/v1/settings/channels/reset')).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Ripristina' }));
    await waitFor(() => expect(sent(requests, 'POST', '/v1/settings/channels/reset')).toHaveLength(1));
    expect(await screen.findByText('Canali ripristinati al .env.')).toBeTruthy();
    // La bozza non salvata sparisce con il ripristino
    expect((telegram().getByLabelText(/^Dati che può ricevere/) as HTMLSelectElement).value).toBe('public');
  });

  it('annullare non chiama il reset', async () => {
    const { requests } = setup();
    await ready();
    fireEvent.click(screen.getByRole('button', { name: /Ripristina il \.env/ }));
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Annulla' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(sent(requests, 'POST', '/v1/settings/channels/reset')).toHaveLength(0);
  });
});

describe('scheda Canali: errori', () => {
  const err = (status: number, code: string) => new ApiError(status, { code, message: 'testo del backend' }, 'testo del backend');

  it('i codici 409 noti hanno un messaggio italiano, non il testo del backend', () => {
    for (const code of ['confirm_required', 'no_secret_key']) {
      expect(settingsErrorMessage(err(409, code))).toBe(SETTINGS_ERROR_MESSAGES[code]);
      expect(settingsErrorMessage(err(409, code)).length).toBeGreaterThan(20);
    }
    expect(settingsErrorMessage(err(409, 'altro'))).toBe('testo del backend');
    expect(settingsErrorMessage(new ApiError(404, 'x', 'x'))).toBe('Sezione non trovata: aggiorna la scheda.');
    expect(settingsErrorMessage(new ApiError(422, 'campo non valido', 'campo non valido'))).toBe('campo non valido');
  });

  it('un 409 no_secret_key si vede come avviso', async () => {
    setup({ patch: () => conflict('no_secret_key') });
    await ready();
    fireEvent.change(screen.getByLabelText('Token del bot'), { target: { value: 'x:y' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salva Telegram' }));
    expect((await screen.findByRole('alert')).textContent).toBe(SETTINGS_ERROR_MESSAGES.no_secret_key);
  });

  it('un 422 mostra il testo del backend e non cancella la bozza', async () => {
    setup({ patch: () => jsonResponse({ detail: 'reply_timeout_seconds: fuori intervallo' }, 422) });
    await ready();
    fireEvent.change(general().getByLabelText(/^Attesa massima/), { target: { value: '600' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salva le impostazioni generali' }));
    expect((await screen.findByRole('alert')).textContent).toBe('reply_timeout_seconds: fuori intervallo');
    expect((general().getByLabelText(/^Attesa massima/) as HTMLInputElement).value).toBe('600');
  });

  it('un errore nel caricamento si vede come avviso', async () => {
    mockBackend({ 'GET /v1/settings/channels': () => jsonResponse({ detail: 'down' }, 500) });
    render(<ChannelsTab />);
    expect((await screen.findByRole('alert')).textContent).toBe('Canali non caricati: down');
  });
});
