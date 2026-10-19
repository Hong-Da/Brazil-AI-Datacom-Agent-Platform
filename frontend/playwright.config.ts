import { defineConfig, devices } from '@playwright/test'

/**
 * 端到端测试：scripts/e2e_server.py 建一个临时项目（全量知识库 + 几个样本）并启动服务，浏览器跑真实页面。
 * Windows 用系统自带的 Edge（离线可用）；其他系统用 Playwright 的 Chromium（PLAYWRIGHT_BROWSERS_PATH 在项目内）。
 */
const PORT = Number(process.env.LMESH_E2E_PORT || 9310)
const useEdge = process.platform === 'win32' && !process.env.LMESH_E2E_CHROMIUM

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { outputFolder: '../tests/output/e2e-report', open: 'never' }]],
  // 并行跑多份 e2e 时用 LMESH_E2E_OUT 指定各自的输出目录，避免互相清掉
  outputDir: process.env.LMESH_E2E_OUT || '../tests/output/e2e-results',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...(useEdge ? { channel: 'msedge' } : {}),
  },
  projects: [{ name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, ...(useEdge ? { channel: 'msedge' } : {}) } }],
  webServer: {
    command: `uv run python ../scripts/e2e_server.py --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/v1/health`,
    timeout: 180_000,
    reuseExistingServer: false,
    stdout: 'pipe',
    stderr: 'pipe',
  },
})
