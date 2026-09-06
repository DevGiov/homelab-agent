import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/github-dark.css';
import { Copy, Check, ExternalLink } from 'lucide-react';

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content, className = '' }) => {
  return (
    <div className={`markdown-body space-y-2 text-fg ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={{
          // Styled headings
          h1: ({ children }) => (
            <h1 className="text-base sm:text-lg font-bold text-fg mt-3 mb-2 pb-1 border-b border-border">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-sm sm:text-base font-semibold text-fg/90 mt-2.5 mb-1.5 pb-0.5 border-b border-border/60">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-xs sm:text-sm font-semibold text-accent mt-2 mb-1">
              {children}
            </h3>
          ),
          
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

          // Styled Hyperlinks
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 text-accent hover:underline underline-offset-2 transition font-medium"
            >
              <span>{children}</span>
              <ExternalLink size={11} className="inline shrink-0" />
            </a>
          ),

          // Styled GFM Tables
          table: ({ children }) => (
            <div className="overflow-x-auto my-3 rounded-xl border border-border shadow-sm bg-panel/40 backdrop-blur-md">
              <table className="w-full text-left text-xs border-collapse font-sans">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-panel/70 text-fg font-semibold border-b border-border uppercase text-[10px] tracking-wider">
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
            <th className="px-3 py-2 font-mono font-medium text-accent">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="px-3 py-2 font-mono text-[11px] sm:text-xs leading-relaxed">
              {children}
            </td>
          ),

          // Custom Code Blocks (Inline vs Fenced with Copy Button)
          code: ({ node, className, children, ...props }) => {
            const match = /language-(\w+)/.exec(className || '');
            const rawText = extractText(children).replace(/\n$/, '');

            if (!match && !rawText.includes('\n')) {
              // Inline code snippet
              return (
                <code
                  className="bg-panel/80 border border-border text-accent px-1.5 py-0.5 rounded font-mono text-[11px] sm:text-xs"
                  {...props}
                >
                  {children}
                </code>
              );
            }

            return (
              <CodeBlock language={match ? match[1] : ''} rawCode={rawText}>
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
        <span className="text-[10px] font-semibold uppercase text-accent tracking-wider">
          {language || 'code'}
        </span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 text-[10px] text-fg-muted hover:text-fg transition bg-panel/60 hover:bg-panel px-2 py-0.5 rounded border border-border/60 cursor-pointer"
          title="Copy code to clipboard"
        >
          {copied ? (
            <>
              <Check size={11} className="text-emerald-400" />
              <span className="text-emerald-400 font-medium">Copied!</span>
            </>
          ) : (
            <>
              <Copy size={11} />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Code Body */}
      <pre className="p-3 overflow-x-auto text-fg leading-relaxed font-mono text-[11px] sm:text-xs whitespace-pre hljs bg-bg/40">
        <code className={`hljs ${language ? `language-${language}` : ''}`}>{children}</code>
      </pre>
    </div>
  );
};
