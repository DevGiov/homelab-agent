import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { shallowestHeading } from '../utils/headings';
import { MarkdownRenderer } from './MarkdownRenderer';

describe('titoli del testo', () => {
  it('trova il livello più alto fuori dai blocchi di codice', () => {
    expect(shallowestHeading('testo senza titoli')).toBe(1);
    expect(shallowestHeading('## Uno\n### Due')).toBe(2);
    expect(shallowestHeading('```\n# commento nel codice\n```\n### Solo questo')).toBe(3);
  });

  it('porta il titolo più alto a h3, da qualunque livello parta il testo', () => {
    const tags = (content: string) =>
      [...render(<MarkdownRenderer content={content} />).container.querySelectorAll('h1,h2,h3,h4,h5,h6')].map((h) => h.tagName);
    expect(tags('# Uno\n\n## Due\n\n### Tre')).toEqual(['H3', 'H4', 'H5']);
    expect(tags('## Uno\n\n### Due')).toEqual(['H3', 'H4']);
    expect(tags('#### Uno\n\n###### Due')).toEqual(['H3', 'H5']);
  });

  it('rende le tabelle larghe raggiungibili da tastiera', () => {
    const { getByRole } = render(<MarkdownRenderer content={'| a | b |\n| - | - |\n| 1 | 2 |'} />);
    expect(getByRole('group', { name: 'Tabella' }).getAttribute('tabindex')).toBe('0');
  });

  it('rende i blocchi di codice, che scorrono in orizzontale, raggiungibili da tastiera', () => {
    const { getByRole } = render(<MarkdownRenderer content={'```bash\necho una-riga-molto-lunga\n```'} />);
    const code = getByRole('group', { name: 'Codice bash' });
    expect(code.tagName).toBe('CODE');
    expect(code.getAttribute('tabindex')).toBe('0');
    expect(code.className.split(/\s+/)).toEqual(expect.arrayContaining(['block', 'overflow-x-auto']));
  });

  it('URL e parole lunghe vanno a capo: link in linea e overflow-wrap:anywhere sul testo', () => {
    const url = 'https://esempio.invalid/percorso/molto/lungo/senza/spazi';
    const { container, getByRole } = render(<MarkdownRenderer content={`[${url}](${url}) e \`codice_senza_spazi\``} />);
    expect((container.firstElementChild as HTMLElement).className.split(/\s+/)).toContain('[overflow-wrap:anywhere]');
    const link = getByRole('link', { name: url });
    expect(link.className.split(/\s+/)).not.toContain('inline-flex');
  });
});
