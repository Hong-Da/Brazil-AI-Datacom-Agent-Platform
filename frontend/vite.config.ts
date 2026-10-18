import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

// 构建产物放到 Python 包内，由 FastAPI 提供；开发时把 /api 代理到本机服务（LMESH_DEV_API 可改代理地址）
export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  build: { outDir: '../src/lmesh/web/static', emptyOutDir: true, chunkSizeWarningLimit: 2000 },
  server: { proxy: { '/api': process.env.LMESH_DEV_API || 'http://127.0.0.1:9000' } },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'] },
})
