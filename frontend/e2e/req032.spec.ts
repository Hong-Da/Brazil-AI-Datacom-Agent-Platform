import { expect, test, type APIRequestContext } from '@playwright/test'
import { USER, collectErrors, login } from './helpers'

/** 翻译自定义规则（REQ-032）：普通用户新建规则集 → 测试框 → 保存 → 试运行 → 翻译时选用，译文中看到新名称。 */

async function asrDevice(request: APIRequestContext): Promise<{ id: number; name: string }> {
  const r = await request.get('/api/v1/devices')
  const devs = (await r.json()).data.devices as { id: number; name: string }[]
  return devs.find((d) => d.name.startsWith('PE-ASR920'))!
}

test('翻译规则：建规则集 → 试运行 → 翻译看到改名', async ({ page }) => {
  await login(page, 'zh-CN', USER)
  const errors = collectErrors(page)
  const id = `e2e-rules-${Date.now()}`
  await page.goto('/translate-rules?new=1')
  await expect(page.getByTestId('trs-editor')).toBeVisible()
  await page.getByTestId('trs-id').fill(id)
  await page.getByTestId('trs-add-names').click()
  const row = page.locator('[data-testid="trs-names"] tbody tr').first()
  await row.locator('select').first().selectOption('rp.policy')
  await row.locator('select').nth(1).selectOption('wildcard')
  await page.getByTestId('trs-name-from-0').fill('EXPORT-*')
  await page.getByTestId('trs-name-to-0').fill('RP_EXPORT_{1}')
  // 测试框：后端即时计算
  await page.getByTestId('trs-test-input').fill('EXPORT-LOOPBACK')
  await expect(page.getByTestId('trs-test-result')).toContainText('RP_EXPORT_LOOPBACK', { timeout: 15_000 })
  // 端口映射页签
  await page.getByTestId('trs-tab-ports').click()
  await page.getByTestId('trs-add-ports').click()
  await page.locator('[data-testid="trs-ports"] tbody tr').first().locator('select').first().selectOption('type')
  await page.getByTestId('trs-port-from-0').fill('Port-channel')
  await page.getByTestId('trs-port-to-0').fill('Eth-Trunk')
  await page.getByTestId('trs-save').click()
  await expect(page.getByTestId('trs-notice')).toContainText(id)
  await expect(page.getByTestId(`trs-item-${id}`)).toBeVisible()
  // 试运行：选 ASR 920 设备
  const asr = await asrDevice(page.request)
  await page.getByTestId('trs-run-device').selectOption(String(asr.id))
  await page.getByTestId('trs-run').click()
  await expect(page.getByTestId('trs-report')).toBeVisible({ timeout: 60_000 })
  await page.getByTestId('nr-tab-renames').click()
  await expect(page.getByTestId('nr-renames')).toContainText('RP_EXPORT_')
  // 翻译时选用
  await page.goto(`/translate?device=${asr.id}&to=huawei-atn-v800r025&rules=${id}`)
  await expect(page.getByTestId('tr-rules')).toHaveValue(id)
  await page.getByTestId('tr-run').click()
  await expect(page.getByTestId('tr-naming')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('tr-naming')).toContainText('RP_EXPORT')
  await expect(page.getByTestId('tr-out')).toContainText('route-policy RP_EXPORT_')
  await expect(page.getByTestId('tr-out')).toContainText('interface Eth-Trunk1')
  await expect(page.locator('[data-testid="tr-out"] .l.w-rename').first()).toBeVisible()
  // 清理
  expect((await page.request.delete(`/api/v1/translate-rules/${id}`)).ok()).toBeTruthy()
  expect(errors).toEqual([])
})

test('翻译规则：内置规则集只读，可另存为；暗色主题可读', async ({ page }) => {
  await login(page, 'en')
  const errors = collectErrors(page)
  await page.addInitScript(() => { localStorage.setItem('lmesh-theme', 'dark') })
  await page.goto('/translate-rules?id=atn-to-asr920')
  await expect(page.getByTestId('trs-save')).toBeDisabled()
  await expect(page.getByTestId('trs-delete')).toHaveCount(0)
  await page.getByTestId('trs-tab-ports').click()
  await expect(page.getByTestId('trs-ports')).toBeVisible()
  await page.getByTestId('trs-saveas').click()
  await expect(page.getByTestId('trs-id')).toHaveValue('atn-to-asr920-copy')
  await expect(page.getByTestId('trs-save')).toBeEnabled()
  const text = await page.locator('main').innerText()
  expect(text.match(/\btranslate-rules\.[a-zA-Z][\w.]*/g) ?? []).toEqual([])
  expect(errors).toEqual([])
})
