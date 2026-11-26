// ISS-40: la scheda di approvazione dice perché non si può più decidere (404, 409 già risolta, 410 scaduta)
// e mostra la scadenza, chiudendosi da sola quando arriva.
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/http';
import { jsonResponse, mockBackend } from '../test/backend';
import { closedFromError, closedMessage, formatApprovalDeadline } from '../utils/approvalCard';
import { InlineApprovalCard } from './InlineApprovalCard';

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const ACTIONS = ['No (Rifiuta)', 'Sì (Una volta)', /Sì, in questa chat/, /Sì, sempre/];

function actionButtons(): HTMLButtonElement[] {
  return ACTIONS.map((name) => screen.getByText(name).closest('button') as HTMLButtonElement);
}

const hhmm = (iso: string) =>
  new Intl.DateTimeFormat('it-IT', { hour: '2-digit', minute: '2-digit' }).format(new Date(iso));

function clickDeny(requestId: string, status: number, detail: unknown) {
  const backend = mockBackend({
    [`POST /v1/approvals/${requestId}/resolve`]: () => jsonResponse({ detail }, status),
  });
  render(<InlineApprovalCard requestId={requestId} toolName="list_demo_widgets" />);
  fireEvent.click(screen.getByText('No (Rifiuta)'));
  return backend;
}

describe('risposte di una richiesta che non si può più decidere', () => {
  it('404: non trovata, pulsanti disabilitati', async () => {
    clickDeny('apr_missing', 404, { code: 'not_found', message: "Richiesta 'apr_missing' non trovata" });
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Richiesta non trovata'));
    expect(actionButtons().every((b) => b.disabled)).toBe(true);
    expect(screen.queryByText('Scegli come procedere per questo tool:')).toBeNull();
  });

  it('404 senza codice (backend più vecchio): non trovata', async () => {
    clickDeny('apr_old', 404, "Richiesta 'apr_old' non trovata o già risolta");
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Richiesta non trovata'));
  });

  it('409 già risolta: dice l\'azione registrata', async () => {
    clickDeny('apr_denied', 409, { code: 'already_resolved', action: 'denied', resolved_by: 'user', message: '…' });
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe(
      'Richiesta già risolta (rifiutata). Non accetta altre decisioni.'));
    expect(actionButtons().every((b) => b.disabled)).toBe(true);
    cleanup();
    clickDeny('apr_approved', 409, { code: 'already_resolved', action: 'approved', message: '…' });
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('(approvata)'));
  });

  it('410 scaduta: l\'ora della scadenza e i pulsanti disabilitati', async () => {
    const expires = '2026-11-20T21:38:31+00:00';
    clickDeny('apr_expired', 410, { code: 'expired', expires_at: expires, message: '…' });
    // Non è oggi: con il giorno
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(
      new RegExp(`^Richiesta scaduta il .+ alle ${hhmm(expires)}: il tool non è stato eseguito`)));
    expect(actionButtons().every((b) => b.disabled)).toBe(true);
  });

  it('409 turno in corso: errore temporaneo, la scheda resta decidibile', async () => {
    clickDeny('apr_busy', 409, 'La chat ha un altro turno in corso: fermalo o aspetta che finisca.');
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('altro turno'));
    expect(screen.queryByRole('status')).toBeNull();
    expect(actionButtons().every((b) => !b.disabled)).toBe(true);
  });
});

describe('scadenza sulla scheda', () => {
  it('prima della scadenza "Scade alle", poi si chiude da sola', () => {
    vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'] });
    vi.setSystemTime(new Date('2026-11-20T10:00:00'));
    const expires = new Date('2026-11-20T10:10:00').toISOString();
    render(<InlineApprovalCard requestId="apr_live" toolName="list_demo_widgets" expiresAt={expires} />);
    expect(screen.getByText(`Scade alle ${hhmm(expires)}`)).toBeTruthy();
    expect(actionButtons().every((b) => !b.disabled)).toBe(true);
    act(() => { vi.advanceTimersByTime(9 * 60_000); });
    expect(screen.queryByRole('status')).toBeNull();
    act(() => { vi.advanceTimersByTime(2 * 60_000); });
    expect(screen.getByText(`Scaduta alle ${hhmm(expires)}`)).toBeTruthy();
    expect(screen.getByRole('status').textContent).toContain('Richiesta scaduta');
    expect(actionButtons().every((b) => b.disabled)).toBe(true);
  });

  it('già scaduta quando compare: chiusa senza click e senza chiamate', () => {
    const backend = mockBackend({});
    const expires = new Date(Date.now() - 60_000).toISOString();
    render(<InlineApprovalCard requestId="apr_past" toolName="list_demo_widgets" expiresAt={expires} />);
    expect(screen.getByRole('status').textContent).toContain('Richiesta scaduta');
    expect(actionButtons().every((b) => b.disabled)).toBe(true);
    fireEvent.click(screen.getByText('No (Rifiuta)'));
    expect(backend.requests).toHaveLength(0);
  });

  it('un altro giorno: con la data', () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-11-20T23:50:00'));
    const expires = new Date('2026-11-21T00:20:00').toISOString();
    const day = new Intl.DateTimeFormat('it-IT', { day: 'numeric', month: 'short' }).format(new Date(expires));
    render(<InlineApprovalCard requestId="apr_tomorrow" toolName="list_demo_widgets" expiresAt={expires} />);
    expect(screen.getByText(`Scade il ${day} alle ${hhmm(expires)}`)).toBeTruthy();
  });

  it('una scheda già risolta non mostra la scadenza e non si chiude come scaduta', () => {
    const expires = new Date(Date.now() - 60_000).toISOString();
    render(<InlineApprovalCard requestId="apr_done" toolName="list_demo_widgets" expiresAt={expires}
      isResolvedInitially resolvedActionInitially="deny" />);
    expect(screen.queryByText(/Scad/)).toBeNull();
    expect(screen.getByRole('status').textContent).toContain('Esecuzione rifiutata');
  });

  it('una scadenza non valida non mostra nulla e non chiude la scheda', () => {
    render(<InlineApprovalCard requestId="apr_bad" toolName="list_demo_widgets" expiresAt="domani" />);
    expect(screen.queryByText(/Scad/)).toBeNull();
    expect(actionButtons().every((b) => !b.disabled)).toBe(true);
  });
});

describe('funzioni della scheda', () => {
  it('closedFromError legge il codice, non solo lo stato', () => {
    expect(closedFromError(new ApiError(404, { code: 'not_found' }, 'x'))).toEqual({ code: 'not_found' });
    expect(closedFromError(new ApiError(409, { code: 'already_resolved', action: 'approved' }, 'x')))
      .toEqual({ code: 'already_resolved', action: 'approved' });
    expect(closedFromError(new ApiError(410, { code: 'expired', expires_at: '2026-11-20T21:38:31+00:00' }, 'x')))
      .toEqual({ code: 'expired', expiresAt: '2026-11-20T21:38:31+00:00' });
    expect(closedFromError(new ApiError(410, 'Richiesta scaduta', 'x'))).toEqual({ code: 'expired', expiresAt: null });
    expect(closedFromError(new ApiError(409, 'turno in corso', 'x'))).toBeNull();
    expect(closedFromError(new ApiError(500, { code: 'expired' }, 'x'))).toEqual({ code: 'expired', expiresAt: null });
    expect(closedFromError(new Error('rete'))).toBeNull();
  });

  it('formatApprovalDeadline: prima e dopo la scadenza', () => {
    const now = new Date('2026-11-20T10:00:00');
    const later = new Date('2026-11-20T10:30:00').toISOString();
    expect(formatApprovalDeadline(later, now)).toEqual({ label: `Scade alle ${hhmm(later)}`, expired: false });
    expect(formatApprovalDeadline(later, new Date('2026-11-20T10:30:00'))?.expired).toBe(true);
    expect(formatApprovalDeadline('non una data', now)).toBeNull();
  });

  it('closedMessage: scaduta senza una data leggibile', () => {
    expect(closedMessage({ code: 'expired', expiresAt: null }, new Date())).toBe(
      "Richiesta scaduta: il tool non è stato eseguito. Chiedi di nuovo all'agente se serve ancora.");
    expect(closedMessage({ code: 'already_resolved', action: 'boh' }, new Date())).toBe(
      'Richiesta già risolta. Non accetta altre decisioni.');
  });
});
