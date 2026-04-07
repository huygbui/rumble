import { defineConfig } from 'vite';
import { resolve } from 'path';

// Multi-page Vite app: login at /, voice at /voice.html
export default defineConfig({
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    rollupOptions: {
      input: {
        main:  resolve(__dirname, 'index.html'),
        voice: resolve(__dirname, 'voice.html'),
      },
    },
  },
});
