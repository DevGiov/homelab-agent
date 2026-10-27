// Caricato on demand da MarkdownRenderer: highlight.js e le sue grammatiche restano fuori dal chunk iniziale.
import rehypeHighlight from 'rehype-highlight';
import type { Options } from 'react-markdown';
import 'highlight.js/styles/github-dark.css';

export type RehypePlugins = NonNullable<Options['rehypePlugins']>;

export const highlightPlugins: RehypePlugins = [[rehypeHighlight, { detect: true }]];
