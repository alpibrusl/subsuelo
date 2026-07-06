import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Data (region GeoJSON/PNG/meta) is served from public/ — symlinked to the
// pipeline output at ../out/web. See webapp/README for the dev workflow.
export default defineConfig({
    plugins: [react()],
    // relative base so the built bundle works at a domain root OR a subpath
    // (GitHub Pages /repo/, etc.) without reconfiguration. Region data is fetched
    // with relative URLs (regions/…), so it resolves correctly either way.
    base: "./",
    server: { host: true, port: 5175 },
});
