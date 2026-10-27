import { describe, expect, it } from 'vitest';
import type { FormattedMessage } from '../api/chat';
import {
  applySnapshot,
  diagnosticsOf,
  extractMessageVersion,
  finalizeMessage,
  mirrorToVersion,
  webPrefetchFromEvent,
} from './chatMessages';

const assistant = (patch: Partial<FormattedMessage> = {}): FormattedMessage => ({
  id: 'a1',
  sender: 'assistant',
  content: '',
  timestamp: '10:00',
  ...patch,
});

describe('chatMessages', () => {
  it('finalizeMessage mantiene id e reasoning in streaming se la risposta finale non lo ha', () => {
    const final = finalizeMessage({ thread_id: 't', mode: 'ACT', response: '[Mode: act]\nFatto' }, 'a1', 'pensato');
    expect(final).toMatchObject({ id: 'a1', content: 'Fatto', mode: 'act', reasoning_content: 'pensato' });
    expect(finalizeMessage({ thread_id: 't', mode: 'chat', response: 'x', reasoning_content: 'dal backend' }, 'a1', 'stream').reasoning_content).toBe(
      'dal backend'
    );
  });

  it('applySnapshot sostituisce lo stato accumulato invece di accodarlo', () => {
    const msg = assistant({ content: 'vecchio', tool_used: 'tool_a' });
    expect(applySnapshot(msg, { content: 'stato completo', is_paused: true })).toMatchObject({
      content: 'stato completo',
      tool_used: 'tool_a',
    });
  });

  it('mirrorToVersion copia contenuto e reasoning nella versione in generazione', () => {
    const msg = assistant({
      content: 'nuovo',
      reasoning_content: 'r',
      versions: [{ id: 'v0', content: 'vecchio', timestamp: '' }, { id: 'v1', content: '', timestamp: '' }],
    });
    const mirrored = mirrorToVersion(msg, 1);
    expect(mirrored.versions?.map((v) => v.content)).toEqual(['vecchio', 'nuovo']);
    expect(msg.versions?.[1].content).toBe(''); // nessuna mutazione dell'originale
    expect(mirrorToVersion(msg, 5)).toBe(msg);
  });

  it('extractMessageVersion toglie i campi che non appartengono a una versione', () => {
    const version = extractMessageVersion(assistant({ content: 'x', versions: [], versionIndex: 0 }));
    expect(version).not.toHaveProperty('sender');
    expect(version).not.toHaveProperty('versions');
    expect(version).not.toHaveProperty('versionIndex');
    expect(version.content).toBe('x');
  });

  it('diagnosticsOf mappa i campi della risposta sul pannello diagnostica', () => {
    expect(diagnosticsOf({ tool_used: 't', mode: 'act', plan_steps: ['1'] })).toMatchObject({
      activeTool: 't',
      activeMode: 'act',
      activePlan: ['1'],
    });
    expect(diagnosticsOf(undefined)).toEqual({});
  });

  it('webPrefetchFromEvent segue avvio e completamento della ricerca web', () => {
    const started = webPrefetchFromEvent(undefined, 'web_prefetch.started', {}, 'domanda');
    expect(started).toEqual({ query: 'domanda', success: true, sources: [] });
    expect(webPrefetchFromEvent(started, 'web_prefetch.completed', { provider: 'ddg', latency_ms: 300 }, 'domanda')).toMatchObject({
      query: 'domanda',
      provider_used: 'ddg',
      latency_ms: 300,
    });
    expect(webPrefetchFromEvent(started, 'altro', {}, 'domanda')).toBe(started);
  });
});
