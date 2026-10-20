import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import { collectErrors, expectNoRawKeys, login } from './helpers'

// M8-7（REQ-044）未支持型号的处理：在单独的项目 e2e-m87 里导入合成的 NE8000（版本不匹配任何 Profile 的版本规则）与
// 认不出厂商的配置 → 识别与 Profile（近似、改选、记住为本项目规则；不支持的厂商只存原文）→ 设备列表的来源标记 →
// 更换 Profile 并重新解析 → 型号规则页 → 配置图的近似提示条与只存原文的提示。用例结束删除项目，不影响其他用例。

const input = (p: string) => fileURLToPath(new URL(`../../tests/inputs/configs/${p}`, import.meta.url))
const SLUG = 'e2e-m87'

test('未支持型号：识别与 Profile → 设备页更换 Profile → 型号规则 → 配置图提示', async ({ page }) => {
  test.setTimeout(180_000)
  await login(page)
  const errors = collectErrors(page)
  await page.request.delete(`/api/v1/projects/${SLUG}`)
  const created = await page.request.post('/api/v1/projects', { data: { name: 'M8-7 未支持型号', slug: SLUG } })
  expect(created.ok(), await created.text()).toBeTruthy()
  try {
    await page.goto(`/p/${SLUG}/devices`)
    await page.getByTestId('open-import').click()
    const dlg = page.getByTestId('import-dialog')
    for (const f of ['ne8000/ne8000-x8-01.cfg', 'ne8000/ne8000-x8-02.cfg', 'other/edge-mx-01.conf']) await dlg.getByTestId('file-input').setInputFiles(input(f)) // 每次选一个，列表累加
    await expect(dlg.getByTestId('chosen-files').locator('tr')).toHaveCount(3)
    await dlg.getByTestId('to-level').click()
    await dlg.getByTestId('to-identify').click()

    // 识别与 Profile：NE8000 近似（厂商默认），认不出厂商的文件默认只存原文
    const table = dlg.getByTestId('identify-table')
    await expect(table).toBeVisible()
    const r1 = dlg.getByTestId('identify-row-ne8000-x8-01.cfg')
    await expect(r1).toContainText('近似')
    await expect(r1).toContainText('近似 · 厂商默认')
    await expect(dlg.getByTestId('identify-row-edge-mx-01.conf')).toContainText('不解析（只存原文）')
    await expectNoRawKeys(page)
    // 改选 R023 并记住为本项目规则（第一行默认已展开）
    await dlg.getByTestId('identify-profile-ne8000-x8-01.cfg').selectOption('huawei-atn-v800r023')
    await dlg.getByTestId('identify-remember-ne8000-x8-01.cfg').check()
    await expect(dlg.locator('.remember .hit')).toContainText('2')
    // 暗色主题：识别表的展开行不是白底
    await page.emulateMedia({ colorScheme: 'dark' })
    // 主题随系统切换是异步的（matchMedia 的 change 事件）：等它生效再取色
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await expect.poll(() => dlg.evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe('rgb(255, 255, 255)')
    await page.emulateMedia({ colorScheme: 'light' })
    await dlg.getByTestId('start-import').click()
    const res = dlg.getByTestId('import-results')
    await expect(res).toBeVisible({ timeout: 60_000 })
    await expect(dlg.getByTestId('import-src-NE8000-X8-01')).toContainText('型号规则')
    await expect(dlg.getByTestId('import-src-NE8000-X8-01')).toContainText('已记住')
    await expect(dlg.getByTestId('import-src-NE8000-X8-02')).toContainText('型号规则') // 同批第二台按刚记住的规则选
    await expect(dlg.getByTestId('import-src-edge-mx-01')).toContainText('不支持的厂商')
    await dlg.getByTestId('import-done').click()

    // 设备列表：近似提示、来源标记、不支持的厂商
    await expect(page.getByTestId('approx-notice')).toContainText('2')
    const devTable = page.getByTestId('devices-table')
    await expect(devTable.getByTestId('dev-unsupported')).toHaveCount(1)
    const ne1 = devTable.locator('tr', { has: page.getByText('NE8000-X8-01', { exact: true }) })
    await expect(ne1).toContainText('huawei-atn-v800r023')
    await expect(ne1).toContainText('型号规则')

    // 更换 Profile 并重新解析：候选按试解析排序，选 R025（手工选择）
    await ne1.getByTestId('device-menu').click()
    await ne1.getByTestId('device-act-profile').click()
    const pd = page.getByTestId('profile-dialog')
    await expect(pd.getByTestId('profile-cands')).toContainText('推荐')
    await pd.getByTestId('profile-cand-huawei-atn-v800r025').check()
    await pd.getByTestId('profile-save').click()
    await expect(page.getByTestId('device-action-ok')).toContainText('手工选择')
    await expect(ne1).toContainText('huawei-atn-v800r025')

    // 型号规则页：本项目规则，可试匹配
    await page.goto(`/p/${SLUG}/model-rules`)
    const rules = page.getByTestId('rule-table')
    await expect(rules).toContainText('NE8000-X8-*')
    await expect(rules).toContainText('huawei-atn-v800r023')
    await rules.locator('[data-testid^="rule-edit-"]').first().click()
    await page.getByTestId('rule-test').click()
    await expect(page.getByTestId('rule-test-result')).toContainText('NE8000-X8-02')
    await expectNoRawKeys(page)

    // 配置图：近似提示条；只存原文的设备没有图
    const devs = (await (await page.request.get(`/api/v1/projects/${SLUG}/devices`)).json()).data.devices as { id: number; name: string }[]
    const ne2 = devs.find((d) => d.name === 'NE8000-X8-02')!
    const edge = devs.find((d) => d.name === 'edge-mx-01')!
    await page.goto(`/p/${SLUG}/graph/${ne2.id}`)
    await expect(page.getByTestId('graph-approx')).toContainText('huawei-atn-v800r023')
    await page.goto(`/p/${SLUG}/graph/${edge.id}`)
    await expect(page.getByTestId('graph-raw-only')).toBeVisible()
    expect(errors.filter((e) => !/409/.test(e))).toEqual([])
  } finally {
    await page.request.delete(`/api/v1/projects/${SLUG}`)
  }
})
