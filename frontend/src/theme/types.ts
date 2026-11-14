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
  /** Testo e icone sopra lo sfondo d'accento pieno: almeno 4.5:1 sia su accent sia su accentHover. */
  accentContrast: string;
  /**
   * Testo e icone nel colore d'accento (`text-accent`): almeno 4.5:1 su ogni superficie e sulle tinte dell'accento che gli
   * stanno dietro (`bg-accent/10`…`/25`). Uguale ad `accent` dove l'accento basta, più chiaro o più scuro dove non basta.
   */
  accentText: string;
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
