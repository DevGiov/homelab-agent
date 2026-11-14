// Caricato on demand da MarkdownRenderer: highlight.js e le sue grammatiche restano fuori dal chunk iniziale.
// I colori dei token non vengono da un foglio di highlight.js ma da index.css, che segue il tema (theme/codeColors.ts).
import rehypeHighlight from 'rehype-highlight';
import type { Options } from 'react-markdown';

export type RehypePlugins = NonNullable<Options['rehypePlugins']>;

export const highlightPlugins: RehypePlugins = [[rehypeHighlight, { detect: true }]];
