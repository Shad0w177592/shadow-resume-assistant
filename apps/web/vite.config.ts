import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // The packaged Electron application loads index.html through file://.
  // Relative asset URLs are therefore required; `/assets/...` resolves to the
  // root of the drive and produces a blank window.
  base: "./",
  cacheDir: "../../tmp/vite-cache/web",
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173 },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.ts",
    css: true,
    globals: true,
  },
});
