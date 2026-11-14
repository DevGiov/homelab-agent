// Tipi della configurazione di Tailwind per i test che la leggono (src/theme/themes.test.ts)
import type { Config, PluginCreator } from 'tailwindcss/types/config';

type ThemeColors = Record<string, string | Record<string, string>>;

declare const config: Config & { theme: { extend: { colors: ThemeColors; textColor: ThemeColors } } };
export default config;

/** Colori di stato dei temi chiari: il test chiama `handler` per leggere le regole che genera. */
export declare const lightThemeStatusColors: { handler: PluginCreator };
