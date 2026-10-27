import { describe, expect, it, vi } from 'vitest';
import { chunkedStream } from '../test/backend';
import { readSseEvents } from './sse';

const collect = async (stream: ReadableStream<Uint8Array>) => {
  const events = [];
  for await (const event of readSseEvents(stream)) events.push(event);
  return events;
};

describe('readSseEvents', () => {
  it('decodifica più eventi nello stesso chunk', async () => {
    const stream = chunkedStream(['data: {"type":"content","delta":"a"}\n\ndata: {"type":"content","delta":"b"}\n\n']);
    expect(await collect(stream)).toEqual([
      { type: 'content', delta: 'a' },
      { type: 'content', delta: 'b' },
    ]);
  });

  it('ricompone un evento spezzato tra più chunk', async () => {
    const stream = chunkedStream(['data: {"type":"con', 'tent","del', 'ta":"ciao"}\n', '\n']);
    expect(await collect(stream)).toEqual([{ type: 'content', delta: 'ciao' }]);
  });

  it('ricompone un carattere UTF-8 multibyte spezzato tra due chunk', async () => {
    const bytes = new TextEncoder().encode('data: {"delta":"perché"}\n\n');
    const cut = bytes.indexOf(0xc3) + 1; // a metà della "é"
    expect(await collect(chunkedStream([bytes.slice(0, cut), bytes.slice(cut)]))).toEqual([{ delta: 'perché' }]);
  });

  it('si ferma su [DONE] ignorando quello che segue', async () => {
    const stream = chunkedStream(['data: {"n":1}\n\ndata: [DONE]\n\ndata: {"n":2}\n\n']);
    expect(await collect(stream)).toEqual([{ n: 1 }]);
  });

  it('salta righe non `data:` ed eventi JSON non validi', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const stream = chunkedStream([': keep-alive\n\ndata: {rotto\n\ndata: {"ok":true}\n\n']);
    expect(await collect(stream)).toEqual([{ ok: true }]);
    expect(error).toHaveBeenCalledOnce();
  });

  it('ignora un evento finale incompleto senza riga vuota di chiusura', async () => {
    expect(await collect(chunkedStream(['data: {"n":1}\n\ndata: {"n":2}']))).toEqual([{ n: 1 }]);
  });
});
