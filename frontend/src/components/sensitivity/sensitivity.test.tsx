import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { jsonResponse, mockBackend } from '../../test/backend';
import { InlineApprovalCard } from '../InlineApprovalCard';
import { McpFlowsSection } from '../settings/mcp/McpFlowsSection';
import type { MCPTool } from '../../api/mcp';
import { SensitivityBar, SensitivityHeaderChip } from './SensitivityBar';
import { hiddenCovers, useSensitivityBarVisibility } from './useSensitivityBarVisibility';
import type { SensitivityTag } from '../../utils/sensitivity';
import { useConversationLevel } from './useConversationLevel';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('fascia della conversazione', () => {
  it('compare solo da interni in su, con i motivi', () => {
    const { rerender } = render(<SensitivityBar tag={{ label: 'public', reasons: [] }} />);
    expect(screen.queryByTestId('sensitivity-bar')).toBeNull();
    rerender(<SensitivityBar tag={{ label: 'private', untrusted: true, reasons: ['memoria:fatto', 'untrusted:web_prefetch'] }} />);
    const bar = screen.getByTestId('sensitivity-bar');
    expect(bar.textContent).toContain('Dati privati');
    expect(bar.textContent).toContain('un fatto della memoria');
    expect(bar.textContent).toContain('non attendibile');
  });

  it('su una riga: cosa cambia e il livello scelto solo nei dettagli', () => {
    render(<SensitivityBar tag={{ label: 'private', untrusted: true, reasons: ['memoria:fatto', 'untrusted:web_prefetch'] }} chosen="internal" />);
    const bar = screen.getByTestId('sensitivity-bar');
    expect(bar.textContent).not.toContain('chiedono conferma');
    const toggle = screen.getByRole('button', { name: 'Dettagli' });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(bar.textContent).toContain('chiedono conferma');
    expect(bar.textContent).toContain('Livello scelto per la conversazione: interni');
    expect(bar.textContent).toContain('pagine web della ricerca preventiva');
  });

  it('il livello scelto non compare se coincide con quello effettivo', () => {
    render(<SensitivityBar tag={{ label: 'private', reasons: ['conversazione:private'] }} chosen="private" />);
    fireEvent.click(screen.getByRole('button', { name: 'Dettagli' }));
    expect(screen.getByTestId('sensitivity-bar').textContent).not.toContain('Livello scelto');
  });

  it('il pulsante per nasconderla c\'è solo se qualcuno la può nascondere', () => {
    const onHide = vi.fn();
    const { rerender } = render(<SensitivityBar tag={{ label: 'internal', reasons: [] }} />);
    expect(screen.queryByRole('button', { name: "Nascondi l'avviso" })).toBeNull();
    rerender(<SensitivityBar tag={{ label: 'internal', reasons: [] }} onHide={onHide} />);
    fireEvent.click(screen.getByRole('button', { name: "Nascondi l'avviso" }));
    expect(onHide).toHaveBeenCalledOnce();
  });

  it('la chip dell\'intestazione riapre la fascia', () => {
    const onShow = vi.fn();
    const { rerender } = render(<SensitivityHeaderChip tag={{ label: 'public' }} onShow={onShow} />);
    expect(screen.queryByTestId('sensitivity-header-chip')).toBeNull();
    rerender(<SensitivityHeaderChip tag={{ label: 'private', untrusted: true }} onShow={onShow} />);
    const chip = screen.getByRole('button', { name: "Dati privati, contenuto non attendibile: mostra l'avviso" });
    fireEvent.click(chip);
    expect(onShow).toHaveBeenCalledOnce();
  });
});

describe('fascia nascosta', () => {
  afterEach(() => localStorage.clear());
  const privateTag: SensitivityTag = { label: 'private', reasons: [] };

  it('resta nascosta allo stesso livello o più in basso', () => {
    const hidden = { label: 'private' as const, untrusted: false };
    expect(hiddenCovers(null, privateTag)).toBe(false);
    expect(hiddenCovers(hidden, privateTag)).toBe(true);
    expect(hiddenCovers(hidden, { label: 'internal' })).toBe(true);
    expect(hiddenCovers(hidden, { label: 'secret' })).toBe(false);
    expect(hiddenCovers(hidden, { label: 'internal', untrusted: true })).toBe(false);
    expect(hiddenCovers({ label: 'private', untrusted: true }, { label: 'internal', untrusted: true })).toBe(true);
  });

  it('nasconderla vale anche dopo un ricaricamento e ricompare se il livello sale', () => {
    const { result, rerender } = renderHook(({ tag }) => useSensitivityBarVisibility(tag), { initialProps: { tag: privateTag } });
    expect(result.current.hidden).toBe(false);
    act(() => result.current.hide());
    expect(result.current.hidden).toBe(true);
    rerender({ tag: { label: 'private', untrusted: true, reasons: [] } });
    expect(result.current.hidden).toBe(false);

    const reloaded = renderHook(() => useSensitivityBarVisibility(privateTag));
    expect(reloaded.result.current.hidden).toBe(true);
    act(() => reloaded.result.current.show());
    expect(reloaded.result.current.hidden).toBe(false);
    expect(localStorage.getItem('sensitivity_bar_hidden')).toBeNull();
  });

  it('dopo un ricaricamento ricorda anche il contenuto non attendibile', () => {
    const untrustedTag: SensitivityTag = { label: 'private', untrusted: true, reasons: [] };
    const first = renderHook(() => useSensitivityBarVisibility(untrustedTag));
    act(() => first.result.current.hide());
    const reloaded = renderHook(() => useSensitivityBarVisibility(untrustedTag));
    expect(reloaded.result.current.hidden).toBe(true);
  });

  it('senza storage funziona lo stesso, per la pagina aperta', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('bloccato'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('bloccato'); });
    const { result } = renderHook(() => useSensitivityBarVisibility(privateTag));
    expect(result.current.hidden).toBe(false);
    act(() => result.current.hide());
    expect(result.current.hidden).toBe(true);
  });
});

describe('scheda di uscita dei dati', () => {
  it('mostra destinazione e testo, e non offre "sempre"', () => {
    render(
      <InlineApprovalCard
        requestId="apr_1"
        toolName="web_search"
        argumentsData={{ query: 'nome della persona' }}
        commandPreview="Ricerca: nome della persona"
        commandPrefix="flow:search:web:private"
        riskReason="Dati private (memoria:fatto) verso search:web"
      />
    );
    expect(screen.getByText('Uscita di dati: serve la tua conferma')).toBeTruthy();
    expect(screen.getByText('la ricerca web (motori pubblici)')).toBeTruthy();
    expect(screen.getByText('Testo che uscirebbe:')).toBeTruthy();
    expect(screen.queryByText(/Sì, sempre/)).toBeNull();
    expect(screen.getByText('Sì, in questa chat')).toBeTruthy();
  });

  it('per un comando resta la scheda del guardrail', () => {
    render(<InlineApprovalCard requestId="apr_2" toolName="exec_lxc_command" commandPreview="rm -rf /tmp/x" commandPrefix="rm" />);
    expect(screen.getByText('Autorizzazione Tool Richiesta (Guardrail)')).toBeTruthy();
    expect(screen.getByText(/Sì, sempre/)).toBeTruthy();
  });
});

describe('livello della conversazione', () => {
  it('alzarlo salva subito, abbassarlo chiede conferma', async () => {
    const backend = mockBackend({
      'PUT /v1/threads/t1/sensitivity': (req) => jsonResponse({ thread_id: 't1', sensitivity_level: req.body.level, previous: 'public' }),
    });
    const onSaved = vi.fn();
    const { result } = renderHook(() => useConversationLevel('t1', null, onSaved));
    expect(result.current.level).toBe('public');

    await act(async () => result.current.requestChange('private'));
    await waitFor(() => expect(result.current.level).toBe('private'));
    expect(backend.requests.at(-1)?.body).toEqual({ level: 'private' });
    expect(onSaved).toHaveBeenCalledWith('private');

    act(() => result.current.requestChange('public'));
    expect(result.current.confirmRequest?.message).toContain('Abbassare');
    expect(result.current.level).toBe('private');
    await act(async () => result.current.answer(false));
    expect(result.current.level).toBe('private');

    act(() => result.current.requestChange('public'));
    await act(async () => result.current.answer(true));
    await waitFor(() => expect(result.current.level).toBe('public'));
  });

  it('in una chat nuova resta locale e il primo thread lo tiene', async () => {
    const backend = mockBackend({});
    const { result, rerender } = renderHook(({ id, saved }) => useConversationLevel(id, saved), {
      initialProps: { id: null as string | null, saved: null as 'private' | null },
    });
    await act(async () => result.current.requestChange('private'));
    expect(backend.requests).toHaveLength(0);
    rerender({ id: 'nuovo', saved: null });
    expect(result.current.level).toBe('private');
    rerender({ id: 'altro', saved: null });
    expect(result.current.level).toBe('public');
  });
});

describe('classificazione dei server MCP', () => {
  const tools = [
    { name: 'files__read', server: 'metamcp' },
    { name: 'web__fetch', server: 'metamcp' },
  ] as MCPTool[];

  it('mostra i server del catalogo, segna i non classificati e salva', async () => {
    const backend = mockBackend({
      'GET /v1/security/mcp-flows': () =>
        jsonResponse({
          scopes: [{ scope: 'files', result_label: 'internal', result_untrusted: false, clearance: 'private' }],
          default: { result_label: 'private', result_untrusted: false, clearance: 'public' },
        }),
      'PUT /v1/security/mcp-flows/web': (req) => jsonResponse({ scope: 'web', ...req.body }),
    });
    const notify = vi.fn();
    render(<McpFlowsSection tools={tools} notify={notify} />);
    await waitFor(() => expect(screen.getAllByText('non classificato')).toHaveLength(1));
    expect(screen.getByText('files')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Etichetta dei risultati di web'), { target: { value: 'public' } });
    fireEvent.click(screen.getByLabelText('Risultati non attendibili di web'));
    const saveButtons = screen.getAllByTitle('Salva la classificazione');
    fireEvent.click(saveButtons[1]);
    await waitFor(() => expect(notify).toHaveBeenCalledWith('success', "Server 'web' classificato."));
    const put = backend.requests.find((r) => r.method === 'PUT');
    expect(put?.path).toBe('/v1/security/mcp-flows/web');
    expect(put?.body.result_label).toBe('public');
    expect(put?.body.clearance).toBe('public');
    expect(put?.body.result_untrusted).toBe(true);
  });
});

describe('uscite di dati', () => {
  it('riassume per destinazione e mostra le ultime conferme', async () => {
    const { DataExitsSection } = await import('../settings/DataExitsSection');
    mockBackend({
      'GET /v1/security/flows': () =>
        jsonResponse({
          hours: 168,
          destinations: [
            { destination: 'search:web', allow: 7, ask: 2, approved: 1, deny: 0, lowered: 0, labels: { public: 7, private: 2 } },
            { destination: 'thread', allow: 0, ask: 0, approved: 0, deny: 0, lowered: 1, labels: { public: 1 } },
          ],
          recent: [
            { timestamp: '2026-11-14T10:00:00+00:00', thread_id: 't1', automation_id: null, tool_name: 'web_search', label: 'private',
              destination: 'search:web', flow: 'ask', summary: 'regalo drone' },
          ],
        }),
    });
    render(<DataExitsSection />);
    await waitFor(() => expect(screen.getByText('7 consentite', { exact: false })).toBeTruthy());
    expect(screen.getAllByText('la ricerca web (motori pubblici)').length).toBeGreaterThan(0);
    expect(screen.getByText('regalo drone')).toBeTruthy();
    expect(screen.getByText('conferma chiesta')).toBeTruthy();
    expect(screen.queryByText('thread')).toBeNull();
  });
});
