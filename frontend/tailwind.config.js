/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ivory: "#F5F3ED",
        paper: "#FEFDF9",
        paper2: "#FAF8F2",
        ink: "#292D2B",
        graphite: "#747873",
        sage: "#526B5B",
        sageSoft: "#E7ECE3",
        sageLine: "#CBD6C8",
        terracotta: "#B66F4D",
        fire: "#C77B43",
        fireSoft: "#F3E4D5",
        slate: "#788B91",
        slateSoft: "#E7EDEE",
        line: "#E4E1D9",
        lineSoft: "#EFEDE6",
        rose: "#F4E1DE",
        crimson: "#A33C37",
        amber: "#8D611D",
        amberSoft: "#F4EAD6",
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "system-ui", "sans-serif"],
        serif: ["DM Serif Display", "Source Serif 4", "Georgia", "serif"],
        mono: ["Cascadia Mono", "Consolas", "ui-monospace", "monospace"],
      },
      borderRadius: {
        panel: "3px",
      },
      boxShadow: {
        none: "none",
      },
    },
  },
  plugins: [],
};
