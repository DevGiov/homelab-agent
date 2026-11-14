/** Il livello del titolo più alto del testo (1 = `#`), fuori dai blocchi di codice; 1 se non ce ne sono. */
export function shallowestHeading(content: string): number {
  let level = 7;
  let fenced = false;
  for (const line of content.split('\n')) {
    if (/^ {0,3}(```|~~~)/.test(line)) fenced = !fenced;
    else if (!fenced) {
      const match = /^ {0,3}(#{1,6})\s/.exec(line);
      if (match) level = Math.min(level, match[1].length);
    }
  }
  return level === 7 ? 1 : level;
}
