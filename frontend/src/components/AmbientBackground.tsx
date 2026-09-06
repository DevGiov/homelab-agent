import React from 'react';
import { useTheme } from '../theme/ThemeContext';

export const AmbientBackground: React.FC = () => {
  const { hasGlow, isFrosted } = useTheme();

  if (!hasGlow) return null;

  return (
    <div
      className="fixed inset-0 pointer-events-none overflow-hidden z-0 transition-opacity duration-1000 ease-in-out"
      aria-hidden="true"
    >
      {/* Primary Ambient Orb */}
      <div
        className="absolute -top-[15%] -left-[10%] w-[55vw] h-[55vw] max-w-[850px] max-h-[850px] rounded-full mix-blend-screen filter blur-[90px] animate-ambient-slow opacity-60"
        style={{
          background: 'radial-gradient(circle, var(--glow-1) 0%, rgba(0,0,0,0) 70%)',
          willChange: 'transform',
        }}
      />

      {/* Secondary Ambient Orb */}
      <div
        className="absolute -bottom-[20%] -right-[15%] w-[60vw] h-[60vw] max-w-[900px] max-h-[900px] rounded-full mix-blend-screen filter blur-[100px] animate-ambient-reverse opacity-55"
        style={{
          background: 'radial-gradient(circle, var(--glow-2) 0%, rgba(0,0,0,0) 70%)',
          willChange: 'transform',
        }}
      />

      {/* Subtle Center Accent Orb for Depth */}
      {isFrosted && (
        <div
          className="absolute top-[35%] right-[25%] w-[35vw] h-[35vw] max-w-[500px] max-h-[500px] rounded-full mix-blend-screen filter blur-[80px] animate-ambient-pulse opacity-40"
          style={{
            background: 'radial-gradient(circle, var(--glow-1) 0%, rgba(0,0,0,0) 65%)',
            willChange: 'transform',
          }}
        />
      )}

      {/* Subtle micro-texture overlay for glass refraction */}
      <div
        className="absolute inset-0 opacity-[0.02] pointer-events-none"
        style={{
          backgroundImage: `radial-gradient(circle at 1px 1px, var(--fg) 1px, transparent 0)`,
          backgroundSize: '32px 32px',
        }}
      />
    </div>
  );
};
