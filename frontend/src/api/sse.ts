/** Eventi `data:` di uno stream SSE del backend, già decodificati da JSON; lo stream termina su `[DONE]`. */
export async function* readSseEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<any> {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const chunk = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf('\n\n');

        if (!chunk.startsWith('data: ')) continue;
        const data = chunk.slice(6);
        if (data === '[DONE]') return;
        try {
          yield JSON.parse(data);
        } catch (err) {
          console.error('Evento SSE non valido:', err);
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}
