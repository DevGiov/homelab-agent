import React, { useRef, useEffect, useState, useMemo } from 'react';
import { Lightbulb, ChevronDown } from 'lucide-react';
import { MarkdownRenderer } from './MarkdownRenderer';

interface ReasoningBlockProps {
  content: string;
  isStreaming?: boolean;
}

interface ReasoningPhase {
  title: string;
  body: string;
}

const parsePhases = (rawContent: string): ReasoningPhase[] => {
  if (!rawContent) return [];
  const parts = rawContent.split(/\n\n---\n\n/);
  return parts.map((part, index) => {
    const trimmed = part.trim();
    const match = trimmed.match(/^####\s+([^\n]+)\n*([\s\S]*)$/);
    if (match) {
      return {
        title: match[1].trim(),
        body: match[2].trim(),
      };
    }
    return {
      title: parts.length > 1 ? `Fase ${index + 1}` : '',
      body: trimmed,
    };
  });
};

const ReasoningBlock: React.FC<ReasoningBlockProps> = ({ content, isStreaming }) => {
  const contentRef = useRef<HTMLDivElement>(null);
  const [userHasScrolled, setUserHasScrolled] = useState(false);
  const [isOpen, setIsOpen] = useState(false);

  const phases = useMemo(() => parsePhases(content), [content]);

  // Auto-scroll logic
  useEffect(() => {
    if (!isOpen || !isStreaming || !contentRef.current) return;
    
    const node = contentRef.current;
    
    const scrollObserver = new MutationObserver(() => {
      if (!userHasScrolled) {
        requestAnimationFrame(() => {
          if (node) {
            node.scrollTo({
              top: node.scrollHeight,
              behavior: 'smooth'
            });
          }
        });
      }
    });

    scrollObserver.observe(node, { childList: true, subtree: true, characterData: true });

    return () => scrollObserver.disconnect();
  }, [isOpen, isStreaming, userHasScrolled]);

  // Handle manual scroll to disable auto-scroll
  const handleScroll = () => {
    if (!contentRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = contentRef.current;
    const isAtBottom = Math.abs(scrollHeight - clientHeight - scrollTop) < 10;
    setUserHasScrolled(!isAtBottom);
  };

  // Open automatically when streaming starts
  useEffect(() => {
    if (isStreaming && content.length > 0 && !isOpen) {
      setIsOpen(true);
    }
  }, [isStreaming, content.length]);

  if (!content || !content.trim()) return null;

  return (
    <details 
      className="mb-3 glass-card border border-border/80 rounded-xl overflow-hidden [&_summary::-webkit-details-marker]:hidden group transition-all duration-200 shadow-sm"
      open={isOpen}
      onToggle={(e) => setIsOpen((e.target as HTMLDetailsElement).open)}
    >
      <summary className="px-3.5 py-2.5 cursor-pointer flex items-center justify-between text-xs text-fg-muted font-medium hover:bg-panel hover:text-fg transition-colors select-none">
        <div className="flex items-center gap-2.5">
          <Lightbulb size={14} className="text-amber-400 animate-pulse" />
          <span className="font-medium">
            {isStreaming ? (
              phases.length > 1 ? `Thinking (Fase ${phases.length})...` : 'Thinking...'
            ) : (
              phases.length > 1 ? `Processo di Ragionamento (${phases.length} fasi)` : 'Processo di Ragionamento'
            )}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {phases.length > 1 && (
            <span className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-amber-500/10 text-amber-500 border border-amber-500/20">
              {phases.length} fasi
            </span>
          )}
          <ChevronDown size={14} className="group-open:rotate-180 transition-transform duration-300 ease-in-out opacity-70" />
        </div>
      </summary>
      <div 
        ref={contentRef}
        onScroll={handleScroll}
        className="px-4 py-3 text-fg border-t border-border/60 bg-panel/30 text-sm leading-relaxed max-h-[360px] overflow-y-auto custom-scrollbar space-y-3"
      >
        {phases.length > 1 ? (
          phases.map((phase, idx) => (
            <div 
              key={idx} 
              className="p-3 rounded-lg bg-panel/40 border border-border/50 transition-all duration-200"
            >
              <div className="flex items-center gap-2 mb-2 pb-1.5 border-b border-border/30">
                <span className="px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase rounded-full bg-primary/15 text-primary border border-primary/20">
                  Fase {idx + 1}
                </span>
                {phase.title && (
                  <span className="text-xs font-semibold text-fg/90">
                    {phase.title}
                  </span>
                )}
              </div>
              <div className="text-xs sm:text-sm">
                <MarkdownRenderer content={phase.body || '(Nessun dettaglio aggiuntivo)'} />
              </div>
            </div>
          ))
        ) : phases.length === 1 && phases[0].title ? (
          <div>
            <div className="flex items-center gap-2 mb-2 pb-1.5 border-b border-border/30">
              <span className="text-xs font-semibold text-fg/90">
                {phases[0].title}
              </span>
            </div>
            <MarkdownRenderer content={phases[0].body || content} />
          </div>
        ) : (
          <MarkdownRenderer content={content} />
        )}
      </div>
    </details>
  );
};

export default ReasoningBlock;

