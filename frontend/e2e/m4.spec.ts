import { readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { collectErrors, login, TOKEN } from './helpers'

// M4：增量变更、影响分析、拓扑与一致性、割接迁移、安全基线。e2e 服务导入了 ATN、ASR 920（两个版本）和 LAB-ATN-09。

const TOPO_DIR = fileURLToPath(new URL('../../knowledge/samples/topology/', import.meta.url))
const TOPO_FILES = readdirSync(TOPO_DIR).filter((f) => f.endsWith('.cfg')).map((f) => TOPO_DIR + f)

async function devices(request: APIRequestContext): Promise<{ id: number; name: string; versions: number }[]> {
  const r = await request.get('/api/v1/devices', { headers: { Authorization: `Bearer ${TOKEN}` } })
  return (await r.json()).data.devices
}

/** 页面上不应出现 M4 页面未翻译的文案键 */
async function expectNoM4Keys(page: Page): Promise<void> {
  const text = await page.locator('main').innerText()
  const raw = text.match(/\b(change|impact|topology|migration|baseline)\.(?!json\b)[a-zA-Z][\w.]*\b/g)
  expect(raw ?? [], `未翻译的文案键：${raw?.join(', ')}`).toEqual([])
}

test('导航：变更与分析两组入口', async ({ page }) => {
  await login(page)
  await page.goto('/')
  for (const n of ['change', 'migration', 'impact', 'topology', 'consistency', 'baseline']) await expect(page.getByTestId(`nav-${n}`)).toBeVisible()
  await page.getByTestId('nav-consistency').click()
  await expect(page).toHaveURL(/\/consistency/)
})

test('增量变更：ASR 920 两个版本 → 分块脚本、依赖说明、回滚对应、复检通过、下载', async ({ page, request }) => {
  await login(page)
  const errors = collectErrors(page)
  const asr = (await devices(request)).find((d) => d.versions >= 2)!
  await page.goto(`/change?device=${asr.id}&run=1`)
  await expect(page.getByTestId('chg-verify')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('chg-verify')).toContainText('复检通过')
  const lines = page.locator('[data-testid="chg-script"] .sl')
  await expect(lines.first()).toContainText('configure terminal')
  await expect(lines.last()).toContainText('end')
  // 选中一条有前置的命令：详情给出“排在谁之后”，回滚脚本中对应行高亮
  const withDeps = page.locator('[data-testid="chg-script"] .sl.k-cmd[data-seq]')
  expect(await withDeps.count()).toBeGreaterThan(3)
  let found = false
  for (let i = 0; i < (await withDeps.count()) && !found; i++) {
    await withDeps.nth(i).click()
    if (await page.getByTestId('chg-deps').isVisible()) found = true
  }
  expect(found, '应有带前置依赖的命令').toBe(true)
  await expect(page.getByTestId('chg-detail')).toContainText('为什么有这条命令')
  await expect(page.locator('[data-testid="chg-script"] .sl.is-dep').first()).toBeVisible()
  // 筛选：只看删除
  await page.getByTestId('chg-sum-delete').click()
  await expect(page.locator('[data-testid="chg-script"] .sl.r-del').first()).toBeVisible()
  // 下载脚本与报告
  let dl = page.waitForEvent('download')
  await page.getByTestId('chg-dl-change').click()
  expect((await dl).suggestedFilename()).toMatch(/_change_\d{8}\.txt$/)
  dl = page.waitForEvent('download')
  await page.getByTestId('chg-report-zh').click()
  expect((await dl).suggestedFilename()).toMatch(/\.html$/)
  // 跳到影响分析
  await page.getByTestId('chg-to-impact').click()
  await expect(page.getByTestId('imp-strip')).toBeVisible({ timeout: 30_000 })
  await expectNoM4Keys(page)
  expect(errors).toEqual([])
})

test('影响分析：前缀列表 → 引用它的路由策略与对等体，图与列表联动', async ({ page, request }) => {
  await login(page)
  const errors = collectErrors(page)
  const asr = (await devices(request)).find((d) => d.versions >= 2)!
  await page.goto(`/impact?device=${asr.id}&node=${encodeURIComponent('rp.prefix_list[LOOPBACK-V4]')}`)
  await expect(page.getByTestId('imp-strip')).toBeVisible({ timeout: 30_000 })
  const items = page.getByTestId('imp-item')
  expect(await items.count()).toBeGreaterThan(1)
  await expect(page.getByTestId('imp-list')).toContainText('route-policy')
  await expect(page.getByTestId('impact-canvas')).not.toHaveAttribute('data-nodes', '0')
  await items.first().click()
  await expect(items.first()).toHaveClass(/is-sel/)
  // 反方向：它依赖谁
  await page.getByTestId('imp-dir-down').click()
  await expect(page).toHaveURL(/dir=down/)
  // 搜索加入起点
  await page.getByTestId('imp-add').fill('Loopback0')
  await expect(page.getByTestId('imp-sugg')).toBeVisible()
  await expectNoM4Keys(page)
  expect(errors).toEqual([])
})

test('拓扑与一致性：上传 5 台拓扑样本 → 链路与 13 处不一致，点问题回到拓扑并高亮链路', async ({ page }) => {
  await login(page)
  const errors = collectErrors(page)
  await page.goto('/topology')
  await page.getByTestId('topo-pick').click()
  await page.getByTestId('topo-include').uncheck()
  await page.getByTestId('topo-pick').click()
  await page.getByTestId('topo-upload').setInputFiles(TOPO_FILES)
  await page.getByTestId('topo-run').click()
  await expect(page.getByTestId('topo-strip')).toContainText('5', { timeout: 60_000 })
  await expect(page.getByTestId('topo-canvas')).toHaveAttribute('data-nodes', '5')
  await page.getByTestId('topo-tab-cons').click()
  await expect(page).toHaveURL(/\/consistency/)
  await expect(page.getByTestId('topo-finding')).toHaveCount(13)
  await page.getByTestId('topo-finding').first().click()
  await expect(page).toHaveURL(/\/topology/)
  await expect(page.getByTestId('topo-link')).toBeVisible()
  await expect(page.getByTestId('topo-link')).toContainText('xd.')
  // 导出 CSV
  const dl = page.waitForEvent('download')
  await page.getByTestId('topo-csv').click()
  expect((await dl).suggestedFilename()).toMatch(/^consistency-\d{8}\.csv$/)
  await expectNoM4Keys(page)
  expect(errors).toEqual([])
})

test('割接迁移：ASR 920 → ATN，映射表可改并重新生成，步骤与割接包', async ({ page, request }) => {
  await login(page)
  const errors = collectErrors(page)
  const asr = (await devices(request)).find((d) => d.versions >= 2)!
  await page.goto(`/migration?device=${asr.id}&to=huawei-atn-v800r025&run=1`)
  await expect(page.getByTestId('mig-rail')).toBeVisible({ timeout: 60_000 })
  expect(await page.getByTestId('mig-warn').count()).toBeGreaterThan(0)
  await page.getByTestId('mig-step-map').click()
  const rows = page.getByTestId('mig-map-row')
  expect(await rows.count()).toBeGreaterThan(3)
  // 改一个物理口的目标 → 提示重新生成 → 新配置里出现新接口名
  const phys = rows.filter({ hasText: 'GigabitEthernet0/0/1' }).first()
  await phys.getByTestId('mig-map-input').fill('GigabitEthernet0/2/9')
  await phys.getByTestId('mig-map-input').blur()
  await expect(page.getByTestId('mig-regen')).toBeVisible()
  await page.getByTestId('mig-regen').click()
  await expect(page.getByTestId('mig-regen')).toBeHidden({ timeout: 60_000 })
  await page.getByTestId('mig-step-cfg').click()
  await expect(page.getByTestId('mig-cfg-code')).toContainText('GigabitEthernet0/2/9')
  await page.getByTestId('mig-step-cut').click()
  expect(await page.getByTestId('mig-step').count()).toBeGreaterThan(5)
  await page.getByTestId('mig-step-ver').click()
  await expect(page.getByTestId('mig-verify')).toBeVisible()
  if (await page.getByTestId('mig-zip').isEnabled()) {
    const dl = page.waitForEvent('download')
    await page.getByTestId('mig-zip').click()
    expect((await dl).suggestedFilename()).toMatch(/^migration-.+\.zip$/)
  }
  await expectNoM4Keys(page)
  expect(errors).toEqual([])
})

test('安全基线：矩阵、得分、不符合项与参考命令、规则定义、报告下载', async ({ page }) => {
  await login(page)
  const errors = collectErrors(page)
  await page.goto('/baseline?baseline=strict')
  await expect(page.getByTestId('bl-matrix')).toBeVisible({ timeout: 60_000 })
  expect(await page.getByTestId('bl-col').count()).toBeGreaterThanOrEqual(3)
  await expect(page.getByTestId('bl-cell-fail').first()).toBeVisible()
  await page.getByTestId('bl-cell-fail').first().click()
  await expect(page.getByTestId('bl-failure').first()).toBeVisible()
  await expect(page.getByTestId('bl-remedy')).not.toBeEmpty()
  await page.getByTestId('bl-rule').first().click()
  await expect(page.getByTestId('bl-detail')).toContainText('sec.')
  const dl = page.waitForEvent('download')
  await page.getByTestId('bl-report-en').click()
  expect((await dl).suggestedFilename()).toMatch(/\.html$/)
  await expectNoM4Keys(page)
  expect(errors).toEqual([])
})
