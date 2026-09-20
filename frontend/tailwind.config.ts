import type { Config } from "tailwindcss";

// Colors are CSS variables (see globals.css) so light and dark swap in one place.
const v = (name: string) => `var(--${name})`;

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"),
        surface: v("surface"),
        "surface-2": v("surface-2"),
        ink: v("ink"),
        "ink-2": v("ink-2"),
        muted: v("muted"),
        line: v("line"),
        brand: v("brand"),
        "brand-fg": v("brand-fg"),
        good: v("good-fg"),
        "good-bg": v("good-bg"),
        warn: v("warn-fg"),
        "warn-bg": v("warn-bg"),
        crit: v("crit-fg"),
        "crit-bg": v("crit-bg"),
        s1: v("series-1"),
        s2: v("series-2"),
        s3: v("series-3"),
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
