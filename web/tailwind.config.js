/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        ink: {
          50: "#f8fafc",
          100: "#f1f5f9",
          200: "#e2e8f0",
          300: "#cbd5e1",
          400: "#94a3b8",
          500: "#64748b",
          600: "#475569",
          700: "#334155",
          800: "#1e293b",
          900: "#0f172a",
        },
        // Warm coral palette. Anchors set by the brand colors:
        //   50  = body cream         (#FFF3E3)
        //   200 = inactive surfaces  (#FFD8B8)
        //   500 = tabs / rings       (#FF6B5A)
        //   600 = header / primary   (#E94B35)
        //   900 = outline / shadow   (#7A1F14)
        accent: {
          50: "#fff3e3",
          100: "#ffe9d2",
          200: "#ffd8b8",
          300: "#ffc197",
          400: "#ff9c7a",
          500: "#ff6b5a",
          600: "#e94b35",
          700: "#c03b28",
          800: "#9a2b1c",
          900: "#7a1f14",
        },
        // Single-value highlight for "today" / "selected date" cells. Read
        // as a hotter accent than the brand coral, used sparingly.
        flame: "#ff7a1a",
      },
      // "Plain 400" type. The Tailwind weight classes still render across
      // the codebase, but each tier is shifted down one notch so the
      // overall page reads as quiet body type, not display.
      fontWeight: {
        normal: "400",
        medium: "400",
        semibold: "500",
        bold: "500",
      },
      keyframes: {
        "loader-slide": {
          "0%":   { transform: "translateX(-110%)" },
          "100%": { transform: "translateX(330%)" },
        },
      },
      animation: {
        "loader-slide": "loader-slide 1.1s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
