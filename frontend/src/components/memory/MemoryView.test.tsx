import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Entity, EntityDetail, Episode, Fact, Procedure } from '../../api/memory';
import { jsonResponse, mockBackend } from '../../test/backend';
import { MemoryView } from './MemoryView';

const ct125 = { id: 1, name: 'CT 125', type: 'infrastructure' as const };
const debian = { id: 2, name: 'Debian', type: 'software' as const };
const docker = { id: 3, name: 'Docker', type: 'software' as const };

const facts: Fact[] = [
  { id: 11, content: 'Il CT 125 usa Debian 12', thread_id: 't1', source: 'conversation', created_at: '2026-10-27T13:32:08+00:00', entities: [ct125, debian] },
  { id: 10, content: "L'agente gira su Docker nel CT 125", thread_id: null, source: 'manual', created_at: '2026-10-26T10:00:00+00:00', entities: [ct125, docker] },
];
const entities: Entity[] = [
  { ...ct125, fact_count: 2 },
  { ...debian, fact_count: 1 },
  { ...docker, fact_count: 1 },
];
const ct125Detail: EntityDetail = { ...entities[0], related: [{ ...debian, shared: 1 }, { ...docker, shared: 1 }] };

function setup() {
  return mockBackend(
    {
      'GET /v1/memory/stats': () => jsonResponse({ facts: 2, threads: 1, entities: 3, facts_without_entities: 4, episodes: 1, procedures_proposed: 1 }),
      'GET /v1/memory/facts': (req) => {
        const params = new URLSearchParams(req.search);
        if (params.get('query')) return jsonResponse({ facts: [{ ...facts[0], score: 0.82 }], total: 1 });
        return jsonResponse({ facts, total: 2 });
      },
      'GET /v1/memory/entities': () => jsonResponse(entities),
      'POST /v1/memory/entities/extract': () => jsonResponse({ processed: 4, tagged: 3, remaining: 0 }),
      'DELETE /v1/memory/facts/11': () => new Response(null, { status: 204 }),
      'GET /v1/memory/episodes': () => jsonResponse({ episodes: [episode], total: 1 }),
      'DELETE /v1/memory/episodes/7': () => new Response(null, { status: 204 }),
      'GET /v1/memory/procedures': () => jsonResponse([proposal]),
      'GET /v1/memory/procedures/tools': () => jsonResponse(['proxmox-mcp__exec_lxc_command', 'web_search']),
      'POST /v1/memory/procedures/3/approve': () => jsonResponse({ ...proposal, status: 'approved' }),
      'POST /v1/memory/procedures': (req) => jsonResponse({ ...proposal, ...(req.body as object), id: 4, status: 'approved', source: 'user' }, 201),
      'GET /v1/memory/profile': () => jsonResponse({ content: '', updated_at: null }),
      'PUT /v1/memory/profile': (req) => jsonResponse({ content: (req.body as { content: string }).content.trim(), updated_at: '2026-10-29T12:00:00+00:00' }),
    },
    [
      [/^\/v1\/memory\/entities\/\d+\/merge$/, () => jsonResponse({ ...entities[1], related: [] })],
      [
        /^\/v1\/memory\/entities\/\d+$/,
        (req) => {
          const id = Number(req.path.split('/').pop());
          return jsonResponse(id === 1 ? ct125Detail : { ...entities.find((e) => e.id === id), related: [] });
        },
      ],
      [/^\/v1\/memory\/facts\/\d+$/, (req) => jsonResponse({ ...facts[0], ...req.body })],
    ]
  );
}

const episode: Episode = {
  id: 7,
  content: 'Richiesta: «Riavvia Immich» → …',
  thread_id: 't1',
  mode: 'act',
  task: 'Riavvia Immich sul CT 130',
  outcome: 'fallito',
  steps: [
    { tool: 'get_container_status', args: '{"vmid": 130}', error: null, rolled_back: false },
    { tool: 'exec_lxc_command', args: '{"vmid": 130}', error: 'Unit immich.service not found', rolled_back: false },
  ],
  created_at: '2026-10-29T10:00:00+00:00',
};

const proposal: Procedure = {
  id: 3,
  kind: 'tool_note',
  title: 'Riavvio su CT 125',
  content: 'Riavvia con docker compose, non con systemctl.',
  tool_name: 'proxmox-mcp__exec_lxc_command',
  status: 'proposed',
  source: 'execution',
  thread_id: 't1',
  created_at: '2026-10-29T10:00:00+00:00',
  updated_at: null,
};

const threads = [{ thread_id: 't1', title: 'Setup del CT 125', last_message: null, checkpoint_count: 3 }];

beforeEach(() => {
  // La conferma è un dialogo dell'app: il confirm() nativo non deve più servire
  vi.stubGlobal('confirm', () => false);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('MemoryView', () => {
  it('mostra fatti, entità e thread di origine; un clic su un\'entità filtra e mostra le relazioni', async () => {
    const { requests } = setup();
    const onOpenThread = vi.fn();
    render(<MemoryView threads={threads} onOpenThread={onOpenThread} />);

    expect(await screen.findByText('Il CT 125 usa Debian 12')).toBeTruthy();
    expect(screen.getByText('aggiunto a mano')).toBeTruthy();
    expect(screen.getByText(/fatti non sono mai stati analizzati/)).toBeTruthy();

    fireEvent.click(screen.getByText('Setup del CT 125'));
    expect(onOpenThread).toHaveBeenCalledWith('t1');

    const entityList = screen.getByRole('list', { name: 'Entità' });
    fireEvent.click(within(entityList).getByText('CT 125'));
    const detail = await screen.findByRole('region', { name: 'Entità CT 125' });
    expect(within(detail).getByText(/Infrastruttura · 2 fatti/)).toBeTruthy();
    expect(within(detail).getByText('Docker')).toBeTruthy();
    await waitFor(() => expect(requests.some((r) => r.path === '/v1/memory/facts' && r.search.includes('entity_id=1'))).toBe(true));
  });

  it('modifica testo ed entità di un fatto', async () => {
    const { requests } = setup();
    render(<MemoryView threads={threads} onOpenThread={vi.fn()} />);
    await screen.findByText('Il CT 125 usa Debian 12');

    fireEvent.click(screen.getAllByTitle('Modifica fatto')[0]);
    fireEvent.change(screen.getByLabelText('Testo del fatto'), { target: { value: 'Il CT 125 usa Debian 13' } });
    fireEvent.click(screen.getByLabelText('Rimuovi Debian'));
    fireEvent.change(screen.getByLabelText("Nome dell'entità"), { target: { value: 'Trixie' } });
    fireEvent.change(screen.getByLabelText("Tipo dell'entità"), { target: { value: 'software' } });
    fireEvent.click(screen.getByTitle('Aggiungi entità'));
    fireEvent.click(screen.getByRole('button', { name: 'Salva' }));

    await waitFor(() => expect(requests.some((r) => r.method === 'PUT')).toBe(true));
    const put = requests.find((r) => r.method === 'PUT');
    expect(put?.path).toBe('/v1/memory/facts/11');
    expect(put?.body).toEqual({
      content: 'Il CT 125 usa Debian 13',
      entities: [
        { name: 'CT 125', type: 'infrastructure' },
        { name: 'Trixie', type: 'software' },
      ],
    });
  });

  it('cerca per significato e mostra la pertinenza', async () => {
    const { requests } = setup();
    render(<MemoryView threads={threads} onOpenThread={vi.fn()} />);
    await screen.findByText('Il CT 125 usa Debian 12');

    fireEvent.change(screen.getByLabelText('Cerca nei fatti'), { target: { value: 'che sistema usa il container?' } });
    expect(await screen.findByText('pertinenza 82%')).toBeTruthy();
    expect(requests.some((r) => r.search.includes('query=che+sistema'))).toBe(true);
  });

  it('estrae le entità dei fatti non analizzati e unisce due entità', async () => {
    const { requests } = setup();
    render(<MemoryView threads={threads} onOpenThread={vi.fn()} />);
    await screen.findByText('Il CT 125 usa Debian 12');

    fireEvent.click(screen.getByRole('button', { name: /Estrai entità/ }));
    expect(await screen.findByText(/Entità assegnate a 3 fatti su 4 analizzati/)).toBeTruthy();

    fireEvent.click(within(screen.getByRole('list', { name: 'Entità' })).getByText('Docker'));
    const detail = await screen.findByRole('region', { name: /Entità/ });
    fireEvent.click(within(detail).getByTitle("Unisci in un'altra entità"));
    fireEvent.change(within(detail).getByLabelText('Entità di destinazione'), { target: { value: '2' } });
    fireEvent.click(within(detail).getByRole('button', { name: 'Unisci' }));
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Unisci' }));
    await waitFor(() => expect(requests.some((r) => r.path.endsWith('/merge'))).toBe(true));
    expect(requests.find((r) => r.path.endsWith('/merge'))?.body).toEqual({ into: 2 });
  });

  it('elimina un fatto dopo la conferma nel dialogo dell\'app; annullando non elimina', async () => {
    const { requests } = setup();
    render(<MemoryView threads={threads} onOpenThread={vi.fn()} />);
    await screen.findByText('Il CT 125 usa Debian 12');
    const deletes = () => requests.filter((r) => r.method === 'DELETE');

    fireEvent.click(screen.getAllByTitle('Elimina fatto')[0]);
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Annulla' }));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(deletes()).toEqual([]);

    fireEvent.click(screen.getAllByTitle('Elimina fatto')[0]);
    expect(within(await screen.findByRole('alertdialog')).getByText('Eliminare questo fatto?')).toBeTruthy();
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Elimina' }));
    await waitFor(() => expect(deletes().map((r) => r.path)).toEqual(['/v1/memory/facts/11']));
    expect(await screen.findByText('Fatto eliminato.')).toBeTruthy();
  });

  it('mostra gli episodi con tool, errori ed esito e li elimina dopo la conferma', async () => {
    const { requests } = setup();
    render(<MemoryView threads={threads} onOpenThread={vi.fn()} />);
    await screen.findByText('Il CT 125 usa Debian 12');

    fireEvent.click(screen.getByRole('tab', { name: 'Episodi' }));
    const card = await screen.findByRole('article', { name: 'Episodio 7' });
    expect(within(card).getByText('Riavvia Immich sul CT 130')).toBeTruthy();
    expect(within(card).getByText('fallito')).toBeTruthy();
    expect(within(card).getByText('Unit immich.service not found')).toBeTruthy();
    expect(within(card).getByText('Setup del CT 125')).toBeTruthy();
    expect(screen.queryByRole('list', { name: 'Entità' })?.closest('aside')?.className).not.toContain('md:flex');

    fireEvent.click(within(card).getByTitle('Elimina episodio'));
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Elimina' }));
    await waitFor(() => expect(requests.some((r) => r.method === 'DELETE' && r.path === '/v1/memory/episodes/7')).toBe(true));
    expect(await screen.findByText('Episodio eliminato.')).toBeTruthy();
  });

  it('approva una procedura proposta e ne scrive una nuova', async () => {
    const { requests } = setup();
    render(<MemoryView threads={threads} onOpenThread={vi.fn()} />);
    await screen.findByText('Il CT 125 usa Debian 12');

    const tab = screen.getByRole('tab', { name: /Procedure/ });
    expect(within(tab).getByText('1')).toBeTruthy(); // proposte in attesa
    fireEvent.click(tab);
    const card = await screen.findByRole('article', { name: 'Procedura Riavvio su CT 125' });
    expect(within(card).getByText('da approvare')).toBeTruthy();
    expect(within(card).getByText("ricavata da un'esecuzione")).toBeTruthy();
    fireEvent.click(within(card).getByRole('button', { name: /Approva/ }));
    await waitFor(() => expect(requests.some((r) => r.method === 'POST' && r.path === '/v1/memory/procedures/3/approve')).toBe(true));

    fireEvent.click(screen.getByRole('button', { name: /Procedura/ }));
    fireEvent.change(screen.getByLabelText('Tipo di procedura'), { target: { value: 'plan_template' } });
    expect(screen.queryByLabelText('Tool della nota')).toBeNull();
    fireEvent.change(screen.getByLabelText('Titolo della procedura'), { target: { value: 'Nuovo container' } });
    fireEvent.change(screen.getByLabelText('Contenuto della procedura'), { target: { value: '1. allocate_ip' } });
    fireEvent.click(screen.getByRole('button', { name: 'Aggiungi' }));
    await waitFor(() =>
      expect(requests.find((r) => r.method === 'POST' && r.path === '/v1/memory/procedures')?.body).toEqual({
        kind: 'plan_template',
        title: 'Nuovo container',
        content: '1. allocate_ip',
        tool_name: null,
      })
    );
  });

  it('scrive il profilo che l\'agente legge a ogni turno', async () => {
    const { requests } = setup();
    render(<MemoryView threads={threads} onOpenThread={vi.fn()} />);
    const card = await screen.findByRole('region', { name: "Profilo dell'utente" });
    expect(await within(card).findByText(/Nessun profilo/)).toBeTruthy();

    fireEvent.click(within(card).getByRole('button', { name: /Modifica/ }));
    fireEvent.change(within(card).getByLabelText('Testo del profilo'), { target: { value: 'Uso Debian 12 per i container' } });
    fireEvent.click(within(card).getByRole('button', { name: 'Salva' }));

    expect(await within(card).findByText('Uso Debian 12 per i container')).toBeTruthy();
    expect(requests.find((r) => r.method === 'PUT' && r.path === '/v1/memory/profile')?.body).toEqual({ content: 'Uso Debian 12 per i container' });
  });
});
