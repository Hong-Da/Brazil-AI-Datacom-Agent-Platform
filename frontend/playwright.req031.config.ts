import { defineConfig } from '@playwright/test'
import base from './playwright.config'

/**
 * 不构建前端也能跑的端到端测试：e2e 服务（后端）+ Vite 开发服务（当前源码，/api 代理到 e2e 服务）。
 * 用法：pnpm exec playwright test -c playwright.req031.config.ts e2e/req031.spec.ts
 * 正式回归仍用 playwright.config.ts（构建后的页面）。
 */
const API_PORT = Number(process.env.LMESH_E2E_PORT || 9311)
const WEB_PORT = Number(process.env.LMESH_E2E_WEB_PORT || 5311)

export default defineConfig({
  ...base,
  use: { ...base.use, baseURL: `http://127.0.0.1:${WEB_PORT}` },
  webServer: [
    {
      command: `uv run python ../scripts/e2e_server.py --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
      timeout: 180_000,
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: `node node_modules/vite/bin/vite.js --port ${WEB_PORT} --strictPort --host 127.0.0.1`,
      url: `http://127.0.0.1:${WEB_PORT}/`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { LMESH_DEV_API: `http://127.0.0.1:${API_PORT}` },
    },
  ],
})
