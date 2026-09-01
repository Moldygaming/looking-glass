import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Manrope", "ui-sans-serif", "system-ui"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
        display: ["Syne", "Manrope", "sans-serif"],
      },
      colors: {
        ink: {
          950: "#070b14",
          900: "#0c1220",
          800: "#121a2c",
          700: "#1a2438",
        },
        mist: {
          100: "#e8eef7",
          400: "#8b9bb4",
          500: "#6d7d99",
        },
        glass: "#2ee6c7",
        warn: "#f4b942",
        rose: "#ff6b7a",
      },
      boxShadow: {
        glow: "0 0 40px rgba(46, 230, 199, 0.12)",
      },
    },
  },
  plugins: [],
};

export default config;
