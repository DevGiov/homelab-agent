import React, { createContext, useContext, useEffect, useState, useMemo } from 'react';
import type { ThemeContextType, ThemeDefinition, ThemeId } from './types';
import { THEMES, THEME_LIST, DEFAULT_THEME_ID } from './themes';

const STORAGE_THEME_KEY = 'homelab-agent-theme';
const STORAGE_FROSTED_KEY = 'homelab-agent-frosted';
const STORAGE_GLOW_KEY = 'homelab-agent-glow';

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

function getInitialTheme(): ThemeId {
  try {
    const saved = localStorage.getItem(STORAGE_THEME_KEY) as ThemeId | null;
    if (saved && THEMES[saved]) return saved;
  } catch (e) {
    console.warn('Could not read theme from localStorage:', e);
  }
  return DEFAULT_THEME_ID;
}

function getInitialFrosted(): boolean {
  try {
    const saved = localStorage.getItem(STORAGE_FROSTED_KEY);
    if (saved !== null) return saved === 'true';
  } catch (e) {
    console.warn('Could not read frosted setting from localStorage:', e);
  }
  return true; // Frosted glass enabled by default
}

function getInitialGlow(): boolean {
  try {
    const saved = localStorage.getItem(STORAGE_GLOW_KEY);
    if (saved !== null) return saved === 'true';
  } catch (e) {
    console.warn('Could not read glow setting from localStorage:', e);
  }
  return true; // Ambient glow enabled by default
}

function applyThemeVariables(def: ThemeDefinition, isFrosted: boolean, hasGlow: boolean) {
  const root = document.documentElement;
  const { colors } = def;

  // Inject CSS Custom Properties
  root.style.setProperty('--bg', colors.bg);
  root.style.setProperty('--bg-secondary', colors.bgSecondary);
  root.style.setProperty('--panel', colors.panel);
  root.style.setProperty('--panel-header', colors.panelHeader);
  root.style.setProperty('--border', colors.border);
  root.style.setProperty('--border-subtle', colors.borderSubtle);
  root.style.setProperty('--fg', colors.fg);
  root.style.setProperty('--fg-muted', colors.fgMuted);
  root.style.setProperty('--accent', colors.accent);
  root.style.setProperty('--accent-hover', colors.accentHover);
  root.style.setProperty('--accent-subtle', colors.accentSubtle);
  root.style.setProperty('--user-bubble-bg', colors.userBubble);
  root.style.setProperty('--user-bubble-fg', colors.userBubbleText);
  root.style.setProperty('--agent-bubble-bg', colors.agentBubble);
  root.style.setProperty('--input-bg', colors.inputBg);
  root.style.setProperty('--input-border', colors.inputBorder);
  root.style.setProperty('--glow-1', colors.glow1);
  root.style.setProperty('--glow-2', colors.glow2);

  // Sync mobile meta theme-color
  const metaTheme = document.querySelector('meta[name="theme-color"]');
  if (metaTheme) {
    metaTheme.setAttribute('content', colors.bg);
  }

  // Update body class list
  const body = document.body;
  THEME_LIST.forEach((t) => body.classList.remove(`theme-${t.id}`));
  body.classList.add(`theme-${def.id}`);
  body.classList.toggle('dark', def.isDark);
  body.classList.toggle('theme-frosted', isFrosted);
  body.classList.toggle('theme-glow', hasGlow);
}

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [theme, setThemeState] = useState<ThemeId>(getInitialTheme);
  const [isFrosted, setIsFrostedState] = useState<boolean>(getInitialFrosted);
  const [hasGlow, setHasGlowState] = useState<boolean>(getInitialGlow);

  const themeDef = useMemo(() => THEMES[theme] || THEMES[DEFAULT_THEME_ID], [theme]);

  // Apply theme changes
  useEffect(() => {
    applyThemeVariables(themeDef, isFrosted, hasGlow);
  }, [themeDef, isFrosted, hasGlow]);

  const setTheme = (newTheme: ThemeId) => {
    if (!THEMES[newTheme]) return;
    setThemeState(newTheme);
    try {
      localStorage.setItem(STORAGE_THEME_KEY, newTheme);
    } catch (e) {
      console.warn('Failed to save theme to localStorage:', e);
    }
  };

  const setIsFrosted = (val: boolean) => {
    setIsFrostedState(val);
    try {
      localStorage.setItem(STORAGE_FROSTED_KEY, String(val));
    } catch (e) {
      console.warn('Failed to save frosted to localStorage:', e);
    }
  };

  const setHasGlow = (val: boolean) => {
    setHasGlowState(val);
    try {
      localStorage.setItem(STORAGE_GLOW_KEY, String(val));
    } catch (e) {
      console.warn('Failed to save glow to localStorage:', e);
    }
  };

  const contextValue: ThemeContextType = {
    theme,
    themeDef,
    setTheme,
    isFrosted,
    setIsFrosted,
    hasGlow,
    setHasGlow,
    themes: THEME_LIST,
  };

  return <ThemeContext.Provider value={contextValue}>{children}</ThemeContext.Provider>;
};

export const useTheme = (): ThemeContextType => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};
