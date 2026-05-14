import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      // Forward /api requests to the Django backend during dev.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
      },
      // After the crawler-engine -> Django port, /crawler-api is just a
      // namespaced alias for /api/v1/crawler on the Django backend.
      '/crawler-api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path.replace(/^\/crawler-api/, '/api/v1/crawler'),
      },
      // /crawler-ws used to be a WebSocket proxy to the FastAPI service.
      // Django (WSGI) doesn't natively serve WebSockets, so the live-log
      // stream is now a polling endpoint at /api/v1/crawler/logs. Frontend
      // hooks consume that instead — this proxy entry is removed.
    },
  },
});
