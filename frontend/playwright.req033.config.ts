import { defineConfig } from '@playwright/test'
import base from './playwright.config'

/**
 * REQ-033（内置 AI skill）端到端测试：独立端口与独立数据目录，不与其他 e2e 共用 tests/output/e2e-root。
 * 后端：e2e/req033_server.py（复用 scripts/e2e_server.py 的 prepare，数据在 tests/output/e2e-req033-root，不配置 AI）；
 * 前端：Vite 开发服务（当前源码，/api 代理到后端），不需要先构建。
 * 用法（frontend/ 下，先在项目根 . scripts/env.sh）：pnpm exec playwright test -c playwright.req033.config.ts
 */
const API_PORT = Number(process.env.LMESH_E2E_REQ033_PORT || 9333)
const WEB_PORT = Number(process.env.LMESH_E2E_REQ033_WEB_PORT || 5333)

export default defineConfig({
  ...base,
  testMatch: /req033\.spec\.ts$/,
  reporter: [['list']],
  outputDir: '../tests/output/e2e-req033-results',
  use: { ...base.use, baseURL: `http://127.0.0.1:${WEB_PORT}` },
  webServer: [
    {
      command: `uv run python e2e/req033_server.py --port ${API_PORT}`,
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
