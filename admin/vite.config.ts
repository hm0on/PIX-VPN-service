import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// Префикс пути, под которым админка живёт в production (рандомный slug в .env).
// В dev (локально на :5173) обычно пустой или "/".
// VITE_BASE_PATH должен начинаться и заканчиваться на "/", напр. "/vikih5nh/".
const basePath = process.env.VITE_BASE_PATH?.trim() || '/';

export default defineConfig({
  base: basePath,
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    target: 'es2020',
  },
});
