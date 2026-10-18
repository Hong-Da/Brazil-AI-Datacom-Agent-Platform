import { expect, type Page } from '@playwright/test'

export const TOKEN = 'e2e-token'

/** 预先写入令牌与语言，跳过令牌页。 */
export async function login(page: Page, lang = 'zh-CN'): Promise<void> {
  await page.addInitScript(([t, l]) => {
    localStorage.setItem('lmesh-token', t)
    localStorage.setItem('lmesh-lang', l)
  }, [TOKEN, lang])
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
