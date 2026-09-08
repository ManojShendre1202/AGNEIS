import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built output (dist/) is served directly by nginx (C:\nginx\conf\nginx.conf,
// AGNIES server block on :8050) -- not proxied to a running vite/node
// process. /api/, /admin/, /static/ go to Django (waitress); /ws/ goes
// straight to workflow's websocket stub, bypassing Django entirely.
export default defineConfig({
  plugins: [react()],
});
