export type ThemeId =
  | 'midnight'
  | 'cyberpunk'
  | 'retrowave'
  | 'ocean'
  | 'forest'
  | 'claude'
  | 'dark'
  | 'light';

export interface ThemeColors {
  bg: string;
  bgSecondary: string;
  panel: string;
  panelHeader: string;
  border: string;
  borderSubtle: string;
  fg: string;
  fgMuted: string;
  accent: string;
  accentHover: string;
  accentSubtle: string;
  userBubble: string;
  userBubbleText: string;
  agentBubble: string;
  inputBg: string;
  inputBorder: string;
  glow1: string;
  glow2: string;
}

export interface ThemeDefinition {
  id: ThemeId;
  name: string;
  description: string;
  isDark: boolean;
  swatch: [string, string, string, string]; // bg, panel, accent, fg
  colors: ThemeColors;
}

export interface ThemeContextType {
  theme: ThemeId;
  themeDef: ThemeDefinition;
  setTheme: (id: ThemeId) => void;
  isFrosted: boolean;
  setIsFrosted: (val: boolean) => void;
  hasGlow: boolean;
  setHasGlow: (val: boolean) => void;
  themes: ThemeDefinition[];
}
