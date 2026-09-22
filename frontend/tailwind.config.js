/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    // Полная замена палитры Tailwind, а не extend поверх дефолтной —
    // так в разметке не остаётся соблазна случайно взять bg-blue-500
    // вместо токена темы. Значения читаются из CSS-переменных
    // (src/design-tokens.css), заведённых из реального QSS десктопа.
    colors: {
      transparent: "transparent",
      current: "currentColor",
      white: "#ffffff",
      paper: "var(--color-paper)",
      surface: "var(--color-surface)",
      "surface-alt": "var(--color-surface-alt)",
      hover: "var(--color-hover)",
      border: "var(--color-border)",

      ink: "var(--color-ink)",
      muted: "var(--color-muted)",
      "muted-2": "var(--color-muted-2)",
      faint: "var(--color-faint)",
      disabled: "var(--color-disabled)",

      pine: {
        DEFAULT: "var(--color-pine)",
        hover: "var(--color-pine-hover)",
        active: "var(--color-pine-active)",
        focus: "var(--color-pine-focus)",
        deep: "var(--color-pine-deep)",
      },
      mint: {
        DEFAULT: "var(--color-mint)",
        soft: "var(--color-mint-soft)",
      },
      green: "var(--color-green)",
      oak: {
        DEFAULT: "var(--color-oak)",
        soft: "var(--color-oak-soft)",
      },
      error: {
        DEFAULT: "var(--color-error)",
        soft: "var(--color-error-soft)",
      },
    },
    fontFamily: {
      ui: "var(--font-ui)",
      mono: "var(--font-mono)",
    },
    borderRadius: {
      none: "0px",
      sm: "var(--radius-sm)",
      md: "var(--radius-md)",
      lg: "var(--radius-lg)",
      full: "var(--radius-pill)",
    },
    boxShadow: {
      card: "var(--shadow-card)",
      modal: "var(--shadow-modal)",
    },
    extend: {
      fontSize: {
        // соответствует размерам из styles.py (13/14/15px база вместо
        // тейлвинд-дефолта 16px — Manrope в интерфейсе читается чуть
        // компактнее)
        xs: ["11px", "1.4"],
        sm: ["12px", "1.4"],
        base: ["13px", "1.5"],
        md: ["14px", "1.5"],
        lg: ["15px", "1.5"],
        xl: ["20px", "1.3"],
        "2xl": ["26px", "1.2"],
      },
    },
  },
  plugins: [],
};
