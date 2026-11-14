import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { jsonResponse, mockBackend } from '../../test/backend';
import { InlineApprovalCard } from '../InlineApprovalCard';
import { McpFlowsSection } from '../settings/mcp/McpFlowsSection';
import type { MCPTool } from '../../api/mcp';
import { SensitivityBar } from './SensitivityBar';
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
