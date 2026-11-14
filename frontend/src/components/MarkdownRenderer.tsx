import React, { Suspense, lazy, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Copy, Check, ExternalLink, Calendar } from 'lucide-react';
import { ErrorBoundary } from './ErrorBoundary';
import type { RehypePlugins } from './highlightPlugins';
import { shallowestHeading } from '../utils/headings';

const AutomationProposalCard = lazy(() =>
  import('./automations/AutomationProposalCard').then((m) => ({ default: m.AutomationProposalCard })),
);

let loadedHighlight: RehypePlugins | null = null;
let highlightRequest: Promise<RehypePlugins> | null = null;

/** Carica highlight.js solo quando il contenuto ha un blocco di codice; finché non arriva il codice resta senza colori. */
function useHighlightPlugins(content: string): RehypePlugins | undefined {
  const [plugins, setPlugins] = useState(loadedHighlight);
  const needed = content.includes('```') || content.includes('~~~');

  useEffect(() => {
    if (!needed || plugins) return;
    let active = true;
    highlightRequest ??= import('./highlightPlugins').then((m) => (loadedHighlight = m.highlightPlugins));
    highlightRequest.then((p) => active && setPlugins(p)).catch((err) => console.warn('highlight.js non caricato:', err));
    return () => {
      active = false;
    };
  }, [needed, plugins]);

  return plugins ?? undefined;
}

const HEADING_STYLES: Record<number, string> = {
  1: 'text-base sm:text-lg font-bold text-fg mt-3 mb-2 pb-1 border-b border-border',
  2: 'text-sm sm:text-base font-semibold text-fg/90 mt-2.5 mb-1.5 pb-0.5 border-b border-border/60',
  3: 'text-xs sm:text-sm font-semibold text-accent mt-2 mb-1',
};

/**
 * Titoli del testo: nella pagina stanno sotto il titolo della vista (h2), quindi il più alto diventa h3 e gli altri
 * seguono, qualunque sia il livello da cui parte il testo. L'aspetto resta quello del livello scritto.
 */
function headingComponents(content: string) {
  const shift = 3 - shallowestHeading(content);
  const heading = (written: number) => ({ children }: { children?: React.ReactNode }) =>
    React.createElement(`h${Math.min(6, written + shift)}`, { className: HEADING_STYLES[written] }, children);
  return { h1: heading(1), h2: heading(2), h3: heading(3), h4: heading(4), h5: heading(5), h6: heading(6) };
}

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content, className = '' }) => {
  const rehypePlugins = useHighlightPlugins(content);
  return (
    // overflow-wrap:anywhere: URL e parole senza spazi vanno a capo dentro il fumetto; i blocchi di codice no (white-space: pre),
    // scorrono nel loro riquadro
    <div className={`markdown-body space-y-2 text-fg [overflow-wrap:anywhere] ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={rehypePlugins}
        components={{
          ...headingComponents(content),
          
          // Styled Paragraphs
          p: ({ children }) => (
            <p className="leading-relaxed text-xs sm:text-sm text-fg/90 mb-2 font-sans">
              {children}
            </p>
          ),

          // Styled Unordered & Ordered Lists
          ul: ({ children }) => (
            <ul className="list-disc list-inside space-y-1 my-2 text-xs sm:text-sm text-fg/80 pl-1">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal list-inside space-y-1 my-2 text-xs sm:text-sm text-fg/80 pl-1">
              {children}
            </ol>
          ),
          li: ({ children }) => (
            <li className="leading-normal">{children}</li>
          ),

          // Styled Blockquotes
          blockquote: ({ children }) => (
            <blockquote className="border-l-3 border-accent bg-panel/50 px-3 py-1.5 my-2 rounded-r-lg text-xs sm:text-sm text-fg/80 italic backdrop-blur-sm">
              {children}
            </blockquote>
          ),

          // Styled Hyperlinks & Event Anchors
          a: ({ href, children }) => {
            if (href?.startsWith('#event-')) {
              const eventUid = href.replace('#event-', '');
              return (
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    window.dispatchEvent(new CustomEvent('open-calendar-event', { detail: { eventUid } }));
                  }}
                  className="inline-flex items-center gap-1 text-accent hover:underline underline-offset-2 transition font-medium cursor-pointer"
                  title="Apri nel Calendario"
                >
                  <Calendar size={12} className="inline shrink-0" />
                  <span>{children}</span>
                </button>
              );
            }
            return (
              // In linea, non inline-flex: un link lungo va a capo come il testo invece di allargare il fumetto
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent hover:underline underline-offset-2 transition font-medium"
              >
                {children}
                <ExternalLink size={11} className="inline ml-0.5 align-[-1px]" aria-hidden="true" />
              </a>
            );
          },

          // Styled GFM Tables
          table: ({ children }) => (
            <div
              tabIndex={0}
              role="group"
              aria-label="Tabella"
              className="overflow-x-auto my-3 rounded-xl border border-border shadow-sm bg-panel/40 backdrop-blur-md"
            >
              <table className="w-full text-left text-xs border-collapse font-sans">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-panel/70 text-fg font-semibold border-b border-border uppercase text-xs tracking-wider">
              {children}
            </thead>
          ),
          tbody: ({ children }) => (
            <tbody className="divide-y divide-border/60 text-fg/90">
              {children}
            </tbody>
          ),
          tr: ({ children }) => (
            <tr className="hover:bg-panel/40 transition-colors">
              {children}
            </tr>
          ),
          th: ({ children }) => (
            <th className="px-3 py-2 font-medium text-accent">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="px-3 py-2 text-xs leading-relaxed">
              {children}
            </td>
          ),

          // Custom Code Blocks (Inline vs Fenced with Copy Button)
          code: ({ node: _node, className, children, ...props }) => {
            const match = /language-(\w+)/.exec(className || '');
            const rawText = extractText(children).replace(/\n$/, '');

            if (!match && !rawText.includes('\n')) {
              // Inline code snippet
              return (
                <code
                  className="bg-panel/80 border border-border text-accent px-1.5 py-0.5 rounded font-mono text-xs"
                  {...props}
                >
                  {children}
                </code>
              );
            }

            const lang = match ? match[1] : '';
            const isAutomationProposal =
              lang === 'automation_proposal' ||
              lang === 'automation' ||
              Boolean(className?.includes('automation_proposal') || className?.includes('automation-proposal'));

            if (isAutomationProposal) {
              const rawBlock = (
                <CodeBlock language="json" rawCode={rawText}>
                  {children}
                </CodeBlock>
              );
              return (
                <ErrorBoundary title="Errore anteprima automazione" fallback={rawBlock}>
                  <Suspense fallback={rawBlock}>
                    <AutomationProposalCard rawJson={rawText} />
                  </Suspense>
                </ErrorBoundary>
              );
            }

            return (
              <CodeBlock language={lang} rawCode={rawText}>
                {children}
              </CodeBlock>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};

// Helper to extract text recursively from React nodes (avoids [object Object] from rehype AST)
function extractText(node: React.ReactNode): string {
  if (typeof node === 'string') return node;
  if (typeof node === 'number') return String(node);
  if (!node) return '';
  if (Array.isArray(node)) return node.map(extractText).join('');
  if (React.isValidElement(node) && node.props && (node.props as any).children) {
    return extractText((node.props as any).children);
  }
  return '';
}

// Helper Sub-component for Fenced Code Blocks with Copy Button
const CodeBlock: React.FC<{ language: string; rawCode: string; children: React.ReactNode }> = ({
  language,
  rawCode,
  children,
}) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(rawCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="my-3 rounded-xl border border-border/80 bg-panel/70 backdrop-blur-md overflow-hidden shadow-sm font-mono text-xs">
      {/* Header bar */}
      <div className="bg-panel/90 border-b border-border/60 px-3 py-1.5 flex items-center justify-between text-fg-muted">
        <span className="text-xs font-semibold uppercase text-accent tracking-wider">
          {language || 'codice'}
        </span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 text-xs text-fg-muted hover:text-fg transition bg-panel/60 hover:bg-panel px-2 py-0.5 rounded border border-border/60 cursor-pointer"
          title="Copia il codice negli appunti"
        >
          {copied ? (
            <>
              <Check size={11} className="text-emerald-400" />
              <span className="text-emerald-400 font-medium">Copiato!</span>
            </>
          ) : (
            <>
              <Copy size={11} />
              <span>Copia</span>
            </>
          )}
        </button>
      </div>

      {/* Il codice scorre in orizzontale nel suo riquadro, raggiungibile col Tab per scorrerlo da tastiera */}
      <pre className="p-3 text-fg leading-relaxed font-mono text-xs whitespace-pre hljs bg-bg/40">
        <code
          tabIndex={0}
          role="group"
          aria-label={language ? `Codice ${language}` : 'Codice'}
          className={`hljs block overflow-x-auto ${language ? `language-${language}` : ''}`}
        >
          {children}
        </code>
      </pre>
    </div>
  );
};
