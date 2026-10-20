import { expect, type Page } from '@playwright/test'

export const TOKEN = 'e2e-token'
/** scripts/e2e_server.py 建好的账号（REQ-030）。 */
export const ADMIN = { username: 'e2e-admin', password: 'E2e-admin-pass' }
export const USER = { username: 'e2e-user', password: 'E2e-user-pass' }

/** 用账号登录（会话 Cookie 写进浏览器上下文）并预先写入语言，跳过登录页。默认用管理员。 */
export async function login(page: Page, lang = 'zh-CN', who: { username: string; password: string } = ADMIN): Promise<void> {
  await page.addInitScript((l) => { localStorage.setItem('lmesh-lang', l) }, lang)
  const r = await page.request.post('/api/v1/auth/login', { data: who })
  expect(r.ok(), await r.text()).toBeTruthy()
  // REQ-047：偏好随账号保存。清掉上一个用例留在账号里的偏好，页面打开时改用这里预先写入的本地值（并写入账号）
  const c = await page.request.delete('/api/v1/me/prefs')
  expect(c.ok(), await c.text()).toBeTruthy()
}

/** 页面上不应出现未翻译的文案键（形如 devices.title）。 */
export async function expectNoRawKeys(page: Page): Promise<void> {
  const text = await page.locator('main').innerText()
  const raw = text.match(/\b(dashboard|devices|device-graph|unknown-lines|schema-view|schema-edit|profiles|coverage|review|ingest|releases|ai-settings)\.[a-zA-Z][\w.]*\b/g)
  expect(raw ?? [], `未翻译的文案键：${raw?.join(', ')}`).toEqual([])
}

export function collectErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => { if (m.type() === 'error' && !/favicon|401/.test(m.text())) errors.push(m.text()) })
  return errors
}
