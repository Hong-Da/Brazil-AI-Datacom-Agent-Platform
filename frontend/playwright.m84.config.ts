import { defineConfig } from '@playwright/test'
import base from './playwright.config'

/**
 * M8-4（变更与割接组的 AI skill）端到端测试：独立端口与数据目录，后端 e2e/m84_server.py 配置假的 AI（不联网），
 * 前端用 Vite 开发服务（当前源码），不需要先构建。主配置（没有 AI）下同一个文件只验证入口“不可用”与页面接入。
 * 用法（frontend/ 下，先在项目根 . scripts/env.sh）：pnpm exec playwright test -c playwright.m84.config.ts
 * 并行跑多份时用 LMESH_E2E_ROOT、LMESH_E2E_OUT 与 LMESH_E2E_M84_PORT / LMESH_E2E_M84_WEB_PORT 区分。
 */
const API_PORT = Number(process.env.LMESH_E2E_M84_PORT || 9484)
const WEB_PORT = Number(process.env.LMESH_E2E_M84_WEB_PORT || 5484)

export default defineConfig({
  ...base,
  testMatch: /m84\.spec\.ts$/,
  reporter: [['list']],
  outputDir: process.env.LMESH_E2E_OUT || '../tests/output/e2e-m84-results',
  use: { ...base.use, baseURL: `http://127.0.0.1:${WEB_PORT}` },
  webServer: [
    {
      command: `uv run python e2e/m84_server.py --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
      timeout: 180_000,
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: `pnpm exec vite --port ${WEB_PORT} --strictPort --host 127.0.0.1`,
      url: `http://127.0.0.1:${WEB_PORT}/`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { LMESH_DEV_API: `http://127.0.0.1:${API_PORT}` },
    },
  ],
})
