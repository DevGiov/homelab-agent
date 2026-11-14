// Tipi della configurazione di Tailwind per i test che la leggono (src/theme/themes.test.ts)
import type { Config } from 'tailwindcss';

type ThemeColors = Record<string, string | Record<string, string>>;

declare const config: Config & { theme: { extend: { colors: ThemeColors; textColor: ThemeColors } } };
export default config;
