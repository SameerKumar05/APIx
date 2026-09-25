import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const rawTarget =
    process.env.VITE_PROXY_TARGET ||
    env.VITE_PROXY_TARGET ||
    process.env.BACKEND_PROXY_TARGET ||
    env.BACKEND_PROXY_TARGET ||
    process.env.API_PROXY_TARGET ||
    env.API_PROXY_TARGET ||
    process.env.VITE_API_PROXY_TARGET ||
    env.VITE_API_PROXY_TARGET ||
    process.env.VITE_BACKEND_URL ||
    env.VITE_BACKEND_URL ||
    process.env.BACKEND_URL ||
    env.BACKEND_URL ||
    'http://127.0.0.1:8000';

  const proxyTarget = /^https?:\/\//i.test(rawTarget)
    ? rawTarget
    : /^\d+$/.test(rawTarget)
    ? `http://127.0.0.1:${rawTarget}`
    : `http://${rawTarget}`;

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 3000,
      host: true,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          ws: true,
        },
      },
    },
    preview: {
      port: 4173,
      host: true,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          ws: true,
        },
      },
    },
  };
});
