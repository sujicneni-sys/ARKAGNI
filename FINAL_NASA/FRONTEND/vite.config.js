import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// The dashboard is built to frontend/dist and served by FastAPI at /.
// There is no separate Vite dev server.
export default defineConfig({
    plugins: [react()],
    build: {
        outDir: "dist",
        sourcemap: false,
        chunkSizeWarningLimit: 900,
    },
});
