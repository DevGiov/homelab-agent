import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProviderConfig, ProviderCosts, ProvidersResponse } from '../../../api/providers';
import { jsonResponse, mockBackend, type RecordedRequest } from '../../../test/backend';
import { PROVIDER_ERROR_MESSAGES, providerErrorMessage } from '../../../utils/providerErrors';
import { ApiError } from '../../../api/http';
import { ProvidersTab } from './ProvidersTab';

const llama: ProviderConfig = {
  name: 'llamacpp',
  display_name: 'llama-swap',
  kind: 'openai_compat',
  origin: 'env',
  enabled: true,
  configured: true,
  missing: [],
  cloud: false,
  is_default: true,
  is_fallback: true,
  fields: {
    base_url: { value: 'http://llm.example:8080/v1', source: 'ui' },
    default_model: { value: '', source: 'default' },
    llama_cpp: { value: true, source: 'env' },
  },
  secrets: { api_key: { set: true, source: 'env' } },
  secrets_unreadable: false,
  clearance: { saved: 'private', effective: 'private', granted_for: 'http://llm.example:8080/v1', reset_by_address_change: false },
  healthy: true,
  error: null,
};

const bedrock: ProviderConfig = {
  name: 'bedrock',
  display_name: 'AWS Bedrock',
  kind: 'bedrock',
  origin: 'env',
  enabled: false,
  configured: false,
  missing: ['region', 'models'],
  cloud: true,
  is_default: false,
  is_fallback: false,
  fields: { region: { value: '', source: 'default' }, models: { value: [], source: 'default' } },
  secrets: {
    api_key: { set: false, source: null },
    access_key_id: { set: false, source: null },
    secret_access_key: { set: false, source: null },
    session_token: { set: false, source: null },
  },
  secrets_unreadable: false,
  clearance: { saved: 'public', effective: 'public', granted_for: null, reset_by_address_change: false },
  healthy: null,
  error: null,
};

const custom: ProviderConfig = {
  name: 'vllm-studio',
  display_name: 'vLLM studio',
  kind: 'openai_compat',
  origin: 'ui',
  enabled: true,
  configured: true,
  missing: [],
  cloud: false,
  is_default: false,
  is_fallback: false,
  fields: { base_url: { value: 'http://studio.example:9000/v1', source: 'ui' }, llama_cpp: { value: false, source: 'ui' } },
  secrets: { api_key: { set: true, source: 'ui' } },
  secrets_unreadable: false,
  clearance: { saved: 'public', effective: 'public', granted_for: null, reset_by_address_change: false },
  healthy: false,
  error: 'connessione rifiutata',
};

const costs: ProviderCosts = {
  prices: [{ provider: 'bedrock', model: 'claude-x', input_per_mtok: 3, cached_per_mtok: 0.3, output_per_mtok: 15 }],
  ceilings: { bedrock: 20 },
  spend: { month: '2026-11', by_provider: { bedrock: 4.5 }, total: 4.5 },
  reached: { bedrock: false },
};

interface Options {
  providers?: ProviderConfig[];
  canStoreSecrets?: boolean;
  /** Risposta alle richieste di modifica: di base un provider. */
  patch?: (req: RecordedRequest) => Response;
  /** Risposta alla ricerca dei modelli. */
  discover?: (req: RecordedRequest) => Response;
}

function setup({ providers = [llama, bedrock, custom], canStoreSecrets = true, patch, discover }: Options = {}) {
  const body = (): ProvidersResponse => ({ providers, default_provider: 'llamacpp', fallback_provider: 'llamacpp', can_store_secrets: canStoreSecrets });
  const ok = (req: RecordedRequest) => jsonResponse(providers.find((p) => req.path.includes(`/${p.name}`)) ?? llama);
  const handler = patch ?? ok;
  const backend = mockBackend(
    {
      'GET /v1/providers': () => jsonResponse(body()),
      'GET /v1/providers/costs': () => jsonResponse(costs),
      'GET /v1/models': () => jsonResponse({ providers: [], default: null }),
      'POST /v1/providers': (req) => jsonResponse({ ...custom, name: req.body.name }, 201),
      'PUT /v1/providers/settings': (req) => jsonResponse({ default_provider: 'llamacpp', fallback_provider: 'llamacpp', ...req.body }),
      'PUT /v1/providers/ceilings/total': () => jsonResponse({ scope: 'total', monthly_usd: 50 }),
    },
    [
      ...(discover ? ([[/^\/v1\/providers\/[^/]+\/models\/discover$/, discover]] as Array<[RegExp, (req: RecordedRequest) => Response]>) : []),
      [/^\/v1\/providers\/[^/]+(\/(clearance|reset|test))?$/, handler],
    ]
  );
  render(<ProvidersTab />);
  return backend;
}

const card = (name: string) => within(screen.getByTestId(`provider-${name}`));
const sent = (requests: RecordedRequest[], method: string, path: string) => requests.filter((r) => r.method === method && r.path === path);

async function openCard(name: string, displayName: string) {
  await screen.findByTestId(`provider-${name}`);
  fireEvent.click(screen.getByRole('button', { name: `Apri il provider ${displayName}` }));
}

beforeEach(() => {
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});
afterEach(cleanup);

describe('scheda Provider: elenco', () => {
  it('mostra ogni provider con stato, tipo e livello effettivo', async () => {
    setup();
    await screen.findByTestId('provider-llamacpp');
    const local = card('llamacpp');
    expect(local.getByText('llama-swap')).toBeTruthy();
    expect(local.getByText('Motore locale compatibile OpenAI')).toBeTruthy();
    expect(local.getByText('attivo')).toBeTruthy();
    expect(local.getByText('raggiungibile')).toBeTruthy();
    expect(local.getByText('riceve dati privati')).toBeTruthy();
    expect(local.getByText('predefinito')).toBeTruthy();
    expect(local.getByText('ripiego')).toBeTruthy();

    const cloud = card('bedrock');
    expect(cloud.getByText('disattivato')).toBeTruthy();
    expect(cloud.getByText('non configurato')).toBeTruthy();
    expect(cloud.getByText('non provato')).toBeTruthy();
    expect(card('vllm-studio').getByText('non raggiungibile')).toBeTruthy();
  });

  it("l'interruttore attiva e disattiva il provider", async () => {
    const { requests } = setup();
    await screen.findByTestId('provider-bedrock');
    fireEvent.click(card('bedrock').getByRole('checkbox', { name: 'Attivo: AWS Bedrock' }));
    await waitFor(() => expect(sent(requests, 'PATCH', '/v1/providers/bedrock')).toHaveLength(1));
    expect(sent(requests, 'PATCH', '/v1/providers/bedrock')[0].body).toEqual({ enabled: true });
  });

  it('un campo obbligatorio mancante è detto per nome', async () => {
    setup();
    await openCard('bedrock', 'AWS Bedrock');
    expect(screen.getByText(/mancano: Regione AWS, Modelli/)).toBeTruthy();
  });
});

describe('scheda Provider: campi e origine', () => {
  it("accanto a ogni campo c'è l'origine del valore", async () => {
    setup();
    await openCard('llamacpp', 'llama-swap');
    expect(screen.getByTestId('origin-base_url').textContent).toBe('(dalla UI)');
    expect(screen.getByTestId('origin-default_model').textContent).toBe('(predefinito)');
    expect(screen.getByTestId('origin-llama_cpp').textContent).toBe('(da .env)');
    expect((screen.getByRole('textbox', { name: /^Indirizzo/ }) as HTMLInputElement).value).toBe('http://llm.example:8080/v1');
  });

  it('«torna al .env» manda null per quel campo, e c\'è solo dove il valore viene dalla UI', async () => {
    const { requests } = setup();
    await openCard('llamacpp', 'llama-swap');
    expect(screen.getAllByRole('button', { name: /al \.env$/ })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Riporta «Indirizzo (base URL)» al .env' }));
    await waitFor(() => expect(sent(requests, 'PATCH', '/v1/providers/llamacpp')).toHaveLength(1));
    expect(sent(requests, 'PATCH', '/v1/providers/llamacpp')[0].body).toEqual({ fields: { base_url: null } });
  });

  it('un provider della UI non ha il ritorno al .env', async () => {
    setup();
    await openCard('vllm-studio', 'vLLM studio');
    expect(screen.queryByRole('button', { name: /al \.env$/ })).toBeNull();
  });

  it('salva solo i campi cambiati; i campi lista diventano una lista', async () => {
    const { requests } = setup();
    await openCard('bedrock', 'AWS Bedrock');
    fireEvent.change(screen.getByLabelText(/Regione AWS/), { target: { value: 'eu-west-1' } });
    fireEvent.change(screen.getByLabelText(/^Modelli/), { target: { value: 'm.one\n\n m.two ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salva' }));
    await waitFor(() => expect(sent(requests, 'PATCH', '/v1/providers/bedrock')).toHaveLength(1));
    expect(sent(requests, 'PATCH', '/v1/providers/bedrock')[0].body).toEqual({ fields: { region: 'eu-west-1', models: ['m.one', 'm.two'] } });
  });

  it('Salva resta spento finché non cambia nulla', async () => {
    setup();
    await openCard('llamacpp', 'llama-swap');
    expect((screen.getByRole('button', { name: 'Salva' }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('scheda Provider: indirizzo del provider di ripiego', () => {
  const askFirst = () => {
    // Il backend vuole la conferma quando il salvataggio cambia l'indirizzo del ripiego
    return (req: RecordedRequest) =>
      req.body?.confirm ? jsonResponse(llama) : jsonResponse({ detail: { code: 'confirm_required', message: "Cambiare l'indirizzo del ripiego abbassa il suo livello." } }, 409);
  };

  it('un 409 confirm_required al salvataggio chiede conferma e ripete il PATCH con confirm true', async () => {
    const { requests } = setup({ patch: askFirst() });
    await openCard('llamacpp', 'llama-swap');
    fireEvent.change(card("llamacpp").getByLabelText(/^Indirizzo/), { target: { value: "http://altro.example:8080/v1" } });
    fireEvent.click(screen.getByRole('button', { name: 'Salva' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog.textContent).toContain("abbassa il suo livello");
    expect(sent(requests, 'PATCH', '/v1/providers/llamacpp')).toHaveLength(1);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Conferma' }));
    await waitFor(() => expect(sent(requests, 'PATCH', '/v1/providers/llamacpp')).toHaveLength(2));
    const [first, second] = sent(requests, 'PATCH', '/v1/providers/llamacpp');
    expect(first.body.confirm).toBeUndefined();
    expect(second.body).toEqual({ ...first.body, confirm: true });
  });

  it('annullare la conferma non ripete il PATCH e non dice «salvato»', async () => {
    const { requests } = setup({ patch: askFirst() });
    await openCard('llamacpp', 'llama-swap');
    fireEvent.change(card("llamacpp").getByLabelText(/^Indirizzo/), { target: { value: "http://altro.example:8080/v1" } });
    fireEvent.click(screen.getByRole('button', { name: 'Salva' }));
    const dialog = await screen.findByRole('alertdialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Annulla' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(sent(requests, 'PATCH', '/v1/providers/llamacpp')).toHaveLength(1);
    expect(screen.queryByText('Provider salvato.')).toBeNull();
  });
});

describe('scheda Provider: credenziali in sola scrittura', () => {
  it('mostrano lo stato a parole e nessun valore', async () => {
    setup();
    await openCard('llamacpp', 'llama-swap');
    expect(screen.getByTestId('secret-api_key').textContent).toBe('impostata (da .env)');
    const input = screen.getByLabelText(/^Chiave API/) as HTMLInputElement;
    expect(input.type).toBe('password');
    expect(input.value).toBe('');
    cleanup();

    setup();
    await openCard('vllm-studio', 'vLLM studio');
    expect(screen.getByTestId('secret-api_key').textContent).toBe('impostata dalla UI');
    expect((screen.getByLabelText(/^Chiave API/) as HTMLInputElement).value).toBe('');
    cleanup();

    setup();
    await openCard('bedrock', 'AWS Bedrock');
    expect(screen.getAllByText('non impostata')).toHaveLength(4);
  });

  it('il valore scritto va nel PATCH e poi sparisce dal modulo e dalla pagina', async () => {
    const { requests } = setup();
    await openCard('bedrock', 'AWS Bedrock');
    const input = screen.getByLabelText('Chiave API di Bedrock') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'chiave-segreta-123' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salva' }));
    await waitFor(() => expect(sent(requests, 'PATCH', '/v1/providers/bedrock')).toHaveLength(1));
    expect(sent(requests, 'PATCH', '/v1/providers/bedrock')[0].body).toEqual({ secrets: { api_key: 'chiave-segreta-123' } });
    await waitFor(() => expect((screen.getByLabelText('Chiave API di Bedrock') as HTMLInputElement).value).toBe(''));
    expect(document.body.innerHTML).not.toContain('chiave-segreta-123');
  });

  it('senza can_store_secrets sono spente, con il motivo', async () => {
    setup({ canStoreSecrets: false });
    await openCard('bedrock', 'AWS Bedrock');
    for (const label of ['Chiave API di Bedrock', 'ID della chiave di accesso AWS', 'Segreto della chiave di accesso AWS', 'Token di sessione AWS']) {
      const input = screen.getByLabelText(label) as HTMLInputElement;
      expect(input.disabled).toBe(true);
      expect(input.getAttribute('aria-describedby')).toBeTruthy();
    }
    expect(screen.getByText(/imposta API_SECRET_KEY nel \.env/)).toBeTruthy();
    // I campi che non sono credenziali restano modificabili
    expect((screen.getByLabelText(/Regione AWS/) as HTMLInputElement).disabled).toBe(false);
  });

  it('con can_store_secrets sono attive', async () => {
    setup({ canStoreSecrets: true });
    await openCard('bedrock', 'AWS Bedrock');
    expect((screen.getByLabelText('Chiave API di Bedrock') as HTMLInputElement).disabled).toBe(false);
  });

  it('con un indirizzo nuovo dice di riscrivere la chiave salvata, finché non la si scrive', async () => {
    setup();
    await openCard('vllm-studio', 'vLLM studio');
    const hint = /la chiave salvata è legata a quello vecchio/;
    expect(screen.queryByText(hint)).toBeNull();
    fireEvent.change(screen.getByLabelText(/^Indirizzo/), { target: { value: 'http://altro.example:9000/v1' } });
    expect(screen.getByText(hint)).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/^Chiave API/), { target: { value: 'nuova' } });
    expect(screen.queryByText(hint)).toBeNull();
  });

  it('un 409 secret_required si vede come messaggio chiaro', async () => {
    setup({ patch: () => jsonResponse({ detail: { code: 'secret_required', message: 'x' } }, 409) });
    await openCard('vllm-studio', 'vLLM studio');
    fireEvent.change(screen.getByLabelText(/^Indirizzo/), { target: { value: 'http://altro.example:9000/v1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salva' }));
    expect((await screen.findByRole('alert')).textContent).toBe(PROVIDER_ERROR_MESSAGES.secret_required);
  });

  it('«togli» una credenziale della UI manda null', async () => {
    const { requests } = setup();
    await openCard('vllm-studio', 'vLLM studio');
    fireEvent.click(screen.getByRole('button', { name: /Togli la credenziale/ }));
    await waitFor(() => expect(sent(requests, 'PATCH', '/v1/providers/vllm-studio')).toHaveLength(1));
    expect(sent(requests, 'PATCH', '/v1/providers/vllm-studio')[0].body).toEqual({ secrets: { api_key: null } });
  });

  it('una credenziale illeggibile lo dice', async () => {
    setup({ providers: [{ ...llama, secrets_unreadable: true }] });
    await openCard('llamacpp', 'llama-swap');
    expect(screen.getByText('Credenziale illeggibile, inseriscila di nuovo.')).toBeTruthy();
  });
});

describe('scheda Provider: livello dei dati', () => {
  it("alzare il livello apre un dialogo con l'indirizzo e non manda nulla finché non si conferma", async () => {
    const { requests } = setup();
    await openCard('vllm-studio', 'vLLM studio');
    fireEvent.change(screen.getByLabelText('Livello effettivo'), { target: { value: 'private' } });

    const dialog = await screen.findByRole('alertdialog');
    expect(dialog.textContent).toContain('http://studio.example:9000/v1');
    expect(dialog.textContent).toContain('privati');
    expect(sent(requests, 'PUT', '/v1/providers/vllm-studio/clearance')).toHaveLength(0);

    fireEvent.click(within(dialog).getByRole('button', { name: 'Concedi' }));
    await waitFor(() => expect(sent(requests, 'PUT', '/v1/providers/vllm-studio/clearance')).toHaveLength(1));
    expect(sent(requests, 'PUT', '/v1/providers/vllm-studio/clearance')[0].body).toEqual({ level: 'private', confirm: true });
  });

  it('annullare il dialogo non cambia nulla', async () => {
    const { requests } = setup();
    await openCard('vllm-studio', 'vLLM studio');
    fireEvent.change(screen.getByLabelText('Livello effettivo'), { target: { value: 'internal' } });
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Annulla' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(sent(requests, 'PUT', '/v1/providers/vllm-studio/clearance')).toHaveLength(0);
    expect((screen.getByLabelText('Livello effettivo') as HTMLSelectElement).value).toBe('public');
  });

  it('per Bedrock il dialogo dice la regione', async () => {
    setup({ providers: [{ ...bedrock, fields: { region: { value: 'eu-west-1', source: 'ui' }, models: { value: ['m'], source: 'ui' } } }] });
    await openCard('bedrock', 'AWS Bedrock');
    fireEvent.change(screen.getByLabelText('Livello effettivo'), { target: { value: 'internal' } });
    expect((await screen.findByRole('alertdialog')).textContent).toContain('la regione eu-west-1');
  });

  it('abbassare il livello non chiede conferma e manda confirm false', async () => {
    const { requests } = setup();
    await openCard('llamacpp', 'llama-swap');
    fireEvent.change(screen.getByLabelText('Livello effettivo'), { target: { value: 'internal' } });
    await waitFor(() => expect(sent(requests, 'PUT', '/v1/providers/llamacpp/clearance')).toHaveLength(1));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(sent(requests, 'PUT', '/v1/providers/llamacpp/clearance')[0].body).toEqual({ level: 'internal', confirm: false });
  });

  it("dopo un cambio di indirizzo avvisa che il livello è tornato a «pubblici»", async () => {
    setup({
      providers: [{ ...llama, clearance: { saved: 'private', effective: 'public', granted_for: 'http://old.example/v1', reset_by_address_change: true } }],
    });
    await openCard('llamacpp', 'llama-swap');
    const warning = screen.getByRole('alert');
    expect(warning.textContent).toContain("L'indirizzo è cambiato");
    expect(warning.textContent).toContain('http://old.example/v1');
    expect(warning.textContent).toContain('tornato a «Pubblici»');
  });

  it('senza il cambio non mostra nessun avviso', async () => {
    setup();
    await openCard('llamacpp', 'llama-swap');
    expect(screen.queryByText(/L'indirizzo è cambiato/)).toBeNull();
  });
});

describe('scheda Provider: elimina o ripristina secondo l\'origine', () => {
  it('un provider della UI si elimina, con conferma', async () => {
    const { requests } = setup();
    await openCard('vllm-studio', 'vLLM studio');
    expect(screen.queryByRole('button', { name: /Ripristina il \.env/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Elimina/ }));
    const dialog = await screen.findByRole('alertdialog');
    expect(sent(requests, 'DELETE', '/v1/providers/vllm-studio')).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Elimina' }));
    await waitFor(() => expect(sent(requests, 'DELETE', '/v1/providers/vllm-studio')).toHaveLength(1));
  });

  it('un provider del .env si ripristina, e non si elimina mai', async () => {
    const { requests } = setup();
    await openCard('llamacpp', 'llama-swap');
    expect(screen.queryByRole('button', { name: /^Elimina/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Ripristina il \.env/ }));
    const dialog = await screen.findByRole('alertdialog');
    expect(sent(requests, 'POST', '/v1/providers/llamacpp/reset')).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Ripristina' }));
    await waitFor(() => expect(sent(requests, 'POST', '/v1/providers/llamacpp/reset')).toHaveLength(1));
    expect(sent(requests, 'DELETE', '/v1/providers/llamacpp')).toHaveLength(0);
  });

  it('annullare la conferma non fa nulla', async () => {
    const { requests } = setup();
    await openCard('vllm-studio', 'vLLM studio');
    fireEvent.click(screen.getByRole('button', { name: /Elimina/ }));
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Annulla' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(sent(requests, 'DELETE', '/v1/providers/vllm-studio')).toHaveLength(0);
  });
});

describe('scheda Provider: prova della connessione', () => {
  it('mostra esito, tempo e numero di modelli', async () => {
    const { requests } = setup({
      patch: (req) => (req.path.endsWith('/test') ? jsonResponse({ ok: true, latency_ms: 42, models_count: 7, error: null }) : jsonResponse(llama)),
    });
    await openCard('llamacpp', 'llama-swap');
    fireEvent.click(screen.getByRole('button', { name: 'Prova connessione' }));
    expect(await screen.findByText('Connesso in 42 ms, 7 modelli.')).toBeTruthy();
    // Nessuna modifica: prova la configurazione salvata, senza corpo
    expect(sent(requests, 'POST', '/v1/providers/llamacpp/test')[0].body).toBeUndefined();
  });

  it('con modifiche non salvate prova quelle', async () => {
    const { requests } = setup({
      patch: (req) => jsonResponse(req.path.endsWith('/test') ? { ok: false, latency_ms: null, models_count: null, error: 'timeout' } : llama),
    });
    await openCard('llamacpp', 'llama-swap');
    fireEvent.change(screen.getByRole('textbox', { name: /^Indirizzo/ }), { target: { value: 'http://other.example/v1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Prova connessione' }));
    expect(await screen.findByText('Connessione non riuscita: timeout')).toBeTruthy();
    expect(sent(requests, 'POST', '/v1/providers/llamacpp/test')[0].body).toEqual({ fields: { base_url: 'http://other.example/v1' } });
  });
});

const cloud: ProviderConfig = {
  ...bedrock,
  enabled: true,
  configured: true,
  missing: [],
  fields: { region: { value: 'eu-west-1', source: 'ui' }, models: { value: ['amazon.nova-lite-v1:0'], source: 'ui' } },
  secrets: { ...bedrock.secrets, access_key_id: { set: true, source: 'ui' }, secret_access_key: { set: true, source: 'ui' } },
};

const candidates = [
  { id: 'amazon.nova-lite-v1:0', name: 'Nova Lite', vendor: 'Amazon', kind: 'model', scope: 'region', vision: true, configured: true },
  { id: 'meta.llama3-70b-instruct-v1:0', name: 'Llama 3 70B', vendor: 'Meta', kind: 'model', scope: 'region', vision: false, configured: false },
  { id: 'eu.anthropic.claude-sonnet-4-v1:0', name: 'EU Claude Sonnet 4', vendor: 'Anthropic', kind: 'profile', scope: 'geo', vision: true, configured: false },
  { id: 'global.anthropic.claude-sonnet-4-v1:0', name: 'Global Claude Sonnet 4', vendor: 'Anthropic', kind: 'profile', scope: 'global', vision: true, configured: false },
];

describe('scheda Provider: ricerca dei modelli', () => {
  const found = () => jsonResponse({ models: candidates, error: null });

  it('il pulsante c\'è solo nei provider cloud', async () => {
    const openaiCloud: ProviderConfig = { ...cloud, name: 'nuvola', display_name: 'Nuvola', kind: 'openai_cloud' };
    setup({ providers: [llama, cloud, openaiCloud] });
    await openCard('llamacpp', 'llama-swap');
    expect(card('llamacpp').queryByRole('button', { name: 'Cerca modelli' })).toBeNull();
    await openCard('bedrock', 'AWS Bedrock');
    await openCard('nuvola', 'Nuvola');
    expect(card('bedrock').getByRole('button', { name: 'Cerca modelli' })).toBeTruthy();
    expect(card('nuvola').getByRole('button', { name: 'Cerca modelli' })).toBeTruthy();
  });

  it('i candidati stanno in gruppi per ambito, con fornitore, badge «visione» e gli id configurati spuntati', async () => {
    const { requests } = setup({ providers: [cloud], discover: found });
    await openCard('bedrock', 'AWS Bedrock');
    fireEvent.click(screen.getByRole('button', { name: 'Cerca modelli' }));
    const list = await screen.findByRole('group', { name: 'Modelli trovati' });
    // Nessuna modifica: la ricerca usa la configurazione salvata, senza corpo
    expect(sent(requests, 'POST', '/v1/providers/bedrock/models/discover')[0].body).toBeUndefined();
    for (const heading of ['Solo questa regione', 'Area geografica (profilo tra regioni)', 'Globale']) {
      expect(within(list).getByRole('heading', { name: heading })).toBeTruthy();
    }
    expect(within(list).getByText('Questi profili possono instradare la richiesta in qualunque regione AWS.')).toBeTruthy();
    const region = within(list).getByRole('group', { name: 'Solo questa regione' });
    expect(within(region).getAllByRole('checkbox')).toHaveLength(2);
    expect(within(region).getByText(/Amazon/)).toBeTruthy();
    expect(within(region).getAllByText('visione')).toHaveLength(1);
    expect(within(list).getByRole('group', { name: 'Globale' }).textContent).toContain('global.anthropic.claude-sonnet-4-v1:0');
    expect((within(list).getByRole('checkbox', { name: 'amazon.nova-lite-v1:0' }) as HTMLInputElement).checked).toBe(true);
    expect((within(list).getByRole('checkbox', { name: 'meta.llama3-70b-instruct-v1:0' }) as HTMLInputElement).checked).toBe(false);
    expect(screen.getByText(/Non tutti i modelli rispondono all'API compatibile OpenAI di Bedrock/)).toBeTruthy();
  });

  it('il filtro restringe l\'elenco per id, nome o fornitore', async () => {
    setup({ providers: [cloud], discover: found });
    await openCard('bedrock', 'AWS Bedrock');
    fireEvent.click(screen.getByRole('button', { name: 'Cerca modelli' }));
    await screen.findByRole('group', { name: 'Modelli trovati' });
    fireEvent.change(screen.getByLabelText('Filtra i modelli'), { target: { value: 'meta' } });
    const list = screen.getByRole('group', { name: 'Modelli trovati' });
    expect(within(list).getAllByRole('checkbox').map((c) => c.getAttribute('aria-label'))).toEqual(['meta.llama3-70b-instruct-v1:0']);
    expect(screen.queryByRole('heading', { name: 'Globale' })).toBeNull();
    fireEvent.change(screen.getByLabelText('Filtra i modelli'), { target: { value: 'zzz' } });
    expect(screen.getByText('Nessun modello corrisponde al filtro.')).toBeTruthy();
  });

  it('«Usa i selezionati» cambia la bozza dei modelli e il salvataggio manda i nuovi', async () => {
    const { requests } = setup({ providers: [cloud], discover: found });
    await openCard('bedrock', 'AWS Bedrock');
    fireEvent.click(screen.getByRole('button', { name: 'Cerca modelli' }));
    await screen.findByRole('group', { name: 'Modelli trovati' });
    fireEvent.click(screen.getByRole('checkbox', { name: 'amazon.nova-lite-v1:0' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'eu.anthropic.claude-sonnet-4-v1:0' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'meta.llama3-70b-instruct-v1:0' }));
    fireEvent.click(screen.getByRole('button', { name: 'Usa i selezionati' }));
    // Solo la bozza: nessun PATCH finché non si preme Salva
    expect((screen.getByLabelText(/^Modelli/, { selector: 'textarea' }) as HTMLTextAreaElement).value).toBe('meta.llama3-70b-instruct-v1:0\neu.anthropic.claude-sonnet-4-v1:0');
    expect(sent(requests, 'PATCH', '/v1/providers/bedrock')).toHaveLength(0);
    expect(screen.queryByRole('group', { name: 'Modelli trovati' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Salva' }));
    await waitFor(() => expect(sent(requests, 'PATCH', '/v1/providers/bedrock')).toHaveLength(1));
    expect(sent(requests, 'PATCH', '/v1/providers/bedrock')[0].body).toEqual({
      fields: { models: ['meta.llama3-70b-instruct-v1:0', 'eu.anthropic.claude-sonnet-4-v1:0'] },
    });
  });

  it('con modifiche non salvate le manda come bozza, e un id fuori dai risultati resta scelto', async () => {
    const { requests } = setup({ providers: [cloud], discover: found });
    await openCard('bedrock', 'AWS Bedrock');
    fireEvent.change(card('bedrock').getByRole('textbox', { name: /^Regione AWS/ }), { target: { value: 'us-east-1' } });
    fireEvent.change(screen.getByLabelText(/^Modelli/, { selector: 'textarea' }), { target: { value: 'amazon.nova-lite-v1:0\nmio.modello-a-mano' } });
    fireEvent.click(screen.getByRole('button', { name: 'Cerca modelli' }));
    await screen.findByRole('group', { name: 'Modelli trovati' });
    expect(sent(requests, 'POST', '/v1/providers/bedrock/models/discover')[0].body).toEqual({
      fields: { region: 'us-east-1', models: ['amazon.nova-lite-v1:0', 'mio.modello-a-mano'] },
    });
    expect((screen.getByRole('checkbox', { name: 'mio.modello-a-mano' }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Usa i selezionati' }));
    expect((screen.getByLabelText(/^Modelli/, { selector: 'textarea' }) as HTMLTextAreaElement).value).toBe('mio.modello-a-mano\namazon.nova-lite-v1:0');
  });

  it('un errore della ricerca si vede come avviso, senza elenco', async () => {
    setup({ providers: [cloud], discover: () => jsonResponse({ models: [], error: 'HTTP 403: accesso negato: servono bedrock:ListFoundationModels' }) });
    await openCard('bedrock', 'AWS Bedrock');
    fireEvent.click(screen.getByRole('button', { name: 'Cerca modelli' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Ricerca non riuscita: HTTP 403');
    expect(screen.queryByRole('group', { name: 'Modelli trovati' })).toBeNull();
  });

  it('un errore HTTP si vede come avviso', async () => {
    setup({ providers: [cloud], discover: () => jsonResponse({ detail: { code: 'invalid', message: 'La ricerca non vale per questo tipo.' } }, 422) });
    await openCard('bedrock', 'AWS Bedrock');
    fireEvent.click(screen.getByRole('button', { name: 'Cerca modelli' }));
    expect((await screen.findByRole('alert')).textContent).toContain('Ricerca non riuscita');
  });
});

describe('scheda Provider: prezzi, tetto e spesa', () => {
  it('mostra spesa e tetto del provider e salva un prezzo', async () => {
    const { requests } = setup({
      providers: [{ ...bedrock, fields: { region: { value: 'us-east-1', source: 'ui' }, models: { value: ['claude-x', 'nova'], source: 'ui' } } }],
      patch: (req) => (req.path.includes('/models/') ? jsonResponse({}) : jsonResponse(bedrock)),
    });
    await openCard('bedrock', 'AWS Bedrock');
    expect(card('bedrock').getByText('$4.50')).toBeTruthy();
    expect((screen.getByLabelText('Tetto mensile ($)') as HTMLInputElement).value).toBe('20');
    expect((screen.getByLabelText('Prezzo di ingresso di claude-x') as HTMLInputElement).value).toBe('3');
    expect(screen.getByRole('group', { name: 'Prezzo di nova' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Togli il prezzo di nova' })).toBeNull();

    for (const [label, value] of [['ingresso', '1'], ['cache', '0.1'], ['uscita', '5']]) {
      fireEvent.change(screen.getByLabelText(`Prezzo di ${label} di nova`), { target: { value } });
    }
    fireEvent.click(screen.getByRole('button', { name: 'Salva il prezzo di nova' }));
    await waitFor(() => expect(requests.some((r) => r.method === 'PUT' && r.path === '/v1/providers/bedrock/models/nova/price')).toBe(true));
    const put = requests.find((r) => r.method === 'PUT' && r.path === '/v1/providers/bedrock/models/nova/price');
    expect(put?.body).toEqual({ input_per_mtok: 1, cached_per_mtok: 0.1, output_per_mtok: 5 });
  });

  it('il tetto del provider si salva e si toglie', async () => {
    const { requests } = setup({
      providers: [bedrock],
      patch: (req) => (req.path.includes('/ceilings/') ? jsonResponse({}) : jsonResponse(bedrock)),
    });
    await openCard('bedrock', 'AWS Bedrock');
    fireEvent.change(screen.getByLabelText('Tetto mensile ($)'), { target: { value: '35.5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salva il tetto mensile (Tetto mensile ($))' }));
    await waitFor(() => expect(sent(requests, 'PUT', '/v1/providers/ceilings/bedrock')).toHaveLength(1));
    expect(sent(requests, 'PUT', '/v1/providers/ceilings/bedrock')[0].body).toEqual({ monthly_usd: 35.5 });
    fireEvent.click(screen.getByRole('button', { name: 'Togli il tetto mensile (Tetto mensile ($))' }));
    await waitFor(() => expect(sent(requests, 'DELETE', '/v1/providers/ceilings/bedrock')).toHaveLength(1));
  });
});

describe('scheda Provider: in fondo', () => {
  it('Aggiungi provider manda nome, tipo, nome visibile, campi e credenziali', async () => {
    const { requests } = setup();
    await screen.findByTestId('provider-llamacpp');
    fireEvent.click(screen.getByRole('button', { name: /Aggiungi provider/ }));
    const form = within(screen.getByRole('form', { name: 'Aggiungi provider' }));
    const create = form.getByRole('button', { name: /Crea provider/ }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);

    fireEvent.change(form.getByLabelText(/^Nome \(/), { target: { value: 'Nome Sbagliato' } });
    expect(form.getByText('Nome non valido: usa solo minuscole, cifre e -.')).toBeTruthy();
    expect(create.disabled).toBe(true);

    fireEvent.change(form.getByLabelText(/^Nome \(/), { target: { value: 'cloud-x' } });
    fireEvent.change(form.getByLabelText('Tipo'), { target: { value: 'openai_cloud' } });
    fireEvent.change(form.getByLabelText('Nome visibile'), { target: { value: 'Cloud X' } });
    fireEvent.change(form.getByRole('textbox', { name: /^Indirizzo/ }), { target: { value: 'https://api.example/v1' } });
    fireEvent.change(form.getByLabelText(/^Modelli/), { target: { value: 'a\nb' } });
    fireEvent.change(form.getByLabelText(/^Chiave API/), { target: { value: 'sk-test' } });
    fireEvent.click(create);
    await waitFor(() => expect(sent(requests, 'POST', '/v1/providers')).toHaveLength(1));
    expect(sent(requests, 'POST', '/v1/providers')[0].body).toEqual({
      name: 'cloud-x',
      kind: 'openai_cloud',
      display_name: 'Cloud X',
      fields: { base_url: 'https://api.example/v1', models: ['a', 'b'] },
      secrets: { api_key: 'sk-test' },
    });
  });

  it('il provider predefinito e quello di ripiego si cambiano dai due selettori', async () => {
    const { requests } = setup();
    await screen.findByTestId('provider-llamacpp');
    fireEvent.change(screen.getByLabelText('Provider predefinito'), { target: { value: 'vllm-studio' } });
    await waitFor(() => expect(sent(requests, 'PUT', '/v1/providers/settings')).toHaveLength(1));
    expect(sent(requests, 'PUT', '/v1/providers/settings')[0].body).toEqual({ default_provider: 'vllm-studio' });
  });

  it('il ripiego offre solo provider attivi che ricevono dati privati', async () => {
    setup();
    await screen.findByTestId('provider-llamacpp');
    const options = within(screen.getByLabelText('Provider di ripiego')).getAllByRole('option').map((o) => o.textContent);
    expect(options).toEqual(['llama-swap']);
  });

  it('il tetto totale si salva con lo scope total', async () => {
    const { requests } = setup();
    await screen.findByTestId('provider-llamacpp');
    const group = within(screen.getByRole('group', { name: 'Impostazioni generali dei provider' }));
    fireEvent.change(group.getByLabelText('Tetto mensile totale ($)'), { target: { value: '50' } });
    fireEvent.click(group.getByRole('button', { name: /Salva il tetto mensile/ }));
    await waitFor(() => expect(sent(requests, 'PUT', '/v1/providers/ceilings/total')).toHaveLength(1));
    expect(sent(requests, 'PUT', '/v1/providers/ceilings/total')[0].body).toEqual({ monthly_usd: 50 });
  });
});

describe('errori dell\'API dei provider', () => {
  const conflict = (code: string) => new ApiError(409, { code, message: 'testo del backend' }, 'testo del backend');

  it('ogni codice 409 ha un messaggio italiano chiaro, non il testo del backend', () => {
    for (const code of ['reserved_name', 'name_taken', 'env_provider', 'fallback_provider', 'confirm_required', 'no_secret_key', 'provider_disabled', 'kind_change', 'default_provider', 'not_env_provider', 'secret_required']) {
      const message = providerErrorMessage(conflict(code));
      expect(message).toBe(PROVIDER_ERROR_MESSAGES[code]);
      expect(message).not.toBe('testo del backend');
      expect(message.length).toBeGreaterThan(20);
    }
  });

  it('un codice sconosciuto, un 422 e un 404 passano per il testo del backend o uno generico', () => {
    expect(providerErrorMessage(conflict('altro'))).toBe('testo del backend');
    expect(providerErrorMessage(new ApiError(422, 'campo non valido', 'campo non valido'))).toBe('campo non valido');
    expect(providerErrorMessage(new ApiError(404, 'x', 'x'))).toBe('Provider non trovato: aggiorna la scheda.');
    expect(providerErrorMessage(new Error('rete'))).toBe('rete');
  });

  it('un 409 nella scheda si vede come messaggio chiaro', async () => {
    setup({ patch: () => jsonResponse({ detail: { code: 'no_secret_key', message: 'API_SECRET_KEY missing' } }, 409) });
    await openCard('bedrock', 'AWS Bedrock');
    fireEvent.change(screen.getByLabelText('Chiave API di Bedrock'), { target: { value: 'x' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salva' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(PROVIDER_ERROR_MESSAGES.no_secret_key);
  });

  it('un 409 fallback_provider nelle impostazioni si vede come messaggio chiaro', async () => {
    const { fetchMock } = setup();
    await screen.findByTestId('provider-llamacpp');
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) =>
      String(input).endsWith('/providers/settings') ? jsonResponse({ detail: { code: 'fallback_provider', message: 'x' } }, 409) : original(input, init)
    );
    fireEvent.change(screen.getByLabelText('Provider di ripiego'), { target: { value: 'llamacpp' } });
    fireEvent.change(screen.getByLabelText('Provider predefinito'), { target: { value: 'vllm-studio' } });
    expect((await screen.findByRole('alert')).textContent).toBe(PROVIDER_ERROR_MESSAGES.fallback_provider);
  });

  it('un 409 name_taken alla creazione resta nel modulo', async () => {
    const { fetchMock } = setup();
    await screen.findByTestId('provider-llamacpp');
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) =>
      init?.method === 'POST' && String(input).endsWith('/v1/providers') ? jsonResponse({ detail: { code: 'name_taken', message: 'x' } }, 409) : original(input, init)
    );
    fireEvent.click(screen.getByRole('button', { name: /Aggiungi provider/ }));
    const form = within(screen.getByRole('form', { name: 'Aggiungi provider' }));
    fireEvent.change(form.getByLabelText(/^Nome \(/), { target: { value: 'llamacpp' } });
    fireEvent.click(form.getByRole('button', { name: /Crea provider/ }));
    expect((await form.findByRole('alert')).textContent).toBe(PROVIDER_ERROR_MESSAGES.name_taken);
    expect(screen.getByRole('form', { name: 'Aggiungi provider' })).toBeTruthy();
  });
});
