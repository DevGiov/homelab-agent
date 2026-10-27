import React from 'react';

export const ThinkingIndicator: React.FC = () => (
  <div className="flex items-center gap-2 text-fg-muted py-0.5">
    <div className="flex space-x-1">
      {[0, 150, 300].map((delay) => (
        <div
          key={delay}
          className="w-1.5 h-1.5 sm:w-2 sm:h-2 bg-accent rounded-full animate-bounce"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </div>
    <span className="ml-1 text-[11px] sm:text-xs font-sans">Thinking & executing...</span>
  </div>
);
