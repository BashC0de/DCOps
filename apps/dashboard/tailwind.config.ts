import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // DCOps brand palette — calm blues + accent for criticality.
        ink: {
          50: "#f4f6f8",
          100: "#e3e8ee",
          900: "#0c1116",
          950: "#070a0e",
        },
        accent: {
          ok: "#22c55e",
          warn: "#f59e0b",
          err: "#ef4444",
          info: "#3b82f6",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
