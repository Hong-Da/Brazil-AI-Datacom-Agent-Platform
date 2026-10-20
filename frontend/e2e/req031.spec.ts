import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { collectErrors, login, TOKEN } from './helpers'

// REQ-031 配置检查项目：建项目（ATN-CHANGE-01 作基线）→ 变更脚本边写边查 → 关闭顺序核查 → 按依赖重排 → 对比 → 采用 → 修订记录里恢复。
// e2e 服务默认没有导入 ATN-CHANGE-01，这里先用 API 导入 knowledge/samples/change/atn-base.cfg；
// 用例结束时删除项目与这台设备（REQ-038），不改变后面用例（workflows.spec.ts）看到的设备名单。

const BASE_CFG = fileURLToPath(new URL('../../knowledge/samples/change/atn-base.cfg', import.meta.url))
const SCRIPT = readFileSync(fileURLToPath(new URL('../../tests/inputs/scripts/atn-change-order.txt', import.meta.url)), 'utf-8')
const AUTH = { Authorization: `Bearer ${TOKEN}` }

/** 没有 ATN-CHANGE-01 时导入；返回本用例导入的设备编号（原本就有时为 null，不删除）。 */
async function ensureBaseline(request: APIRequestContext): Promise<number | null> {
  const list = (await (await request.get('/api/v1/devices', { headers: AUTH })).json()).data.devices as { name: string }[]
  if (list.some((d) => d.name === 'ATN-CHANGE-01')) return null
  const r = await request.post('/api/v1/configs', {
    headers: AUTH,
    multipart: { level: 'basic', files: { name: 'atn-base.cfg', mimeType: 'text/plain', buffer: readFileSync(BASE_CFG) } },
  })
  expect(r.ok(), await r.text()).toBeTruthy()
  const file = (await r.json()).data.files[0] as { version_id: number }
  const devs = (await (await request.get('/api/v1/devices', { headers: AUTH })).json()).data.devices as { id: number; latest_version_id: number }[]
  return devs.find((d) => d.latest_version_id === file.version_id)?.id ?? null
}

/** 清理：删除本用例建的项目与导入的设备（设备被项目作基线，先删项目；再用 force 兜底）。 */
async function cleanup(request: APIRequestContext, projectId: number | null, deviceId: number | null): Promise<void> {
  if (projectId !== null) await request.delete(`/api/v1/check-projects/${projectId}`, { headers: AUTH })
  if (deviceId !== null) {
    const r = await request.delete(`/api/v1/devices/${deviceId}?force=true`, { headers: AUTH })
    expect(r.ok(), await r.text()).toBeTruthy()
  }
}

/** 把编辑器内容整体换成 text（一次插入，不触发自动缩进）。 */
async function setEditor(page: Page, text: string): Promise<void> {
  const content = page.getByTestId('cp-editor-content')
  await content.click()
  await page.keyboard.press('Control+A')
  await page.keyboard.insertText(text)
}

async function waitChecked(page: Page): Promise<void> {
  await expect(page.locator('[data-testid="cp-state"][data-state="ok"]')).toBeVisible({ timeout: 30_000 })
}

/** 页面上不应出现本页未翻译的文案键 */
async function expectNoKeys(page: Page): Promise<void> {
  const text = await page.locator('main').innerText()
  const raw = text.match(/\bcheck-projects\.[a-zA-Z][\w.]*\b/g)
  expect(raw ?? [], `未翻译的文案键：${raw?.join(', ')}`).toEqual([])
}

test('配置检查项目：边写边查、顺序核查、按依赖重排、对比、修订恢复', async ({ page, request }) => {
  test.setTimeout(180_000)
  const deviceId = await ensureBaseline(request)
  let projectId: number | null = null
  try {
    await login(page)
    const errors = collectErrors(page)

    // 导航入口在“变更”组：配置检查项目并入项目脚本（M6，/p/<项目>/scripts）
    await page.goto('/')
    await page.getByTestId('nav-scripts').click()
    await expect(page).toHaveURL(/\/p\/[^/]+(\/n\/[^/]+)?\/scripts$/) // M9：只有默认网络时进默认网络

    // 新建变更脚本：基线为本项目的设备，同时建好保存基线与检查设置的脚本组，直接进入编辑器
    await page.getByTestId('scripts-new').click()
    await page.getByTestId('scripts-ns-name').fill('bind-vpn.txt')
    await page.getByTestId('scripts-ns-kind').getByRole('button').first().click()
    await page.getByTestId('scripts-ns-device').selectOption({ label: 'ATN-CHANGE-01' })
    await page.getByTestId('scripts-ns-create').click()
    await expect(page).toHaveURL(/\/p\/[^/]+(\/n\/[^/]+)?\/scripts\/\d+/)
    projectId = Number(/\/scripts\/(\d+)/.exec(page.url())![1])
    await expect(page.getByTestId('cp-basechip')).toContainText('ATN-CHANGE-01')
    await expect(page.getByTestId('cp-fn')).toHaveText('bind-vpn.txt')
    await waitChecked(page)
    await setEditor(page, SCRIPT)

    // 行内问题：行号槽标记 + 问题列表（含顺序错误）
    await expect(page.locator('[data-testid="cp-issue"][data-cat="order"]').first()).toBeVisible({ timeout: 30_000 })
    await waitChecked(page)
    await expect(page.locator('.cm-r31-dots .gdot.error').first()).toBeVisible()
    await expect(page.locator('.cm-r31-sq.error').first()).toBeVisible()
    await expect(page.locator('.cm-r31-moves .mvmark').first()).toBeVisible()
    // 点问题跳到对应行并高亮
    await page.locator('[data-testid="cp-issue"][data-cat="order"]').first().click()
    await expect(page.locator('.cm-line.cm-r31-hl')).toHaveCount(1)
    await expect(page.locator('[data-testid="cp-issue"].is-sel')).toHaveCount(1)
    // 级别筛选
    await page.getByTestId('cp-sev-filter').locator('button').first().click()
    expect(await page.locator('[data-testid="cp-issue"][data-sev="warning"]').count()).toBe(0)
    await page.getByTestId('cp-sev-filter').locator('button').first().click()

    // 关闭顺序核查：顺序类问题消失
    await page.getByTestId('cp-order').click()
    await expect(page.getByTestId('cp-order-off')).toBeVisible()
    await waitChecked(page)
    await expect(page.locator('[data-testid="cp-issue"][data-cat="order"]')).toHaveCount(0)
    await expect(page.locator('.cm-r31-moves .mvmark')).toHaveCount(0)
    // 再打开
    await page.getByTestId('cp-order').click()
    await expect(page.locator('[data-testid="cp-issue"][data-cat="order"]').first()).toBeVisible({ timeout: 30_000 })

    // 按依赖重排：并排对比、移动与原因
    await page.getByTestId('cp-reorder').click()
    await expect(page.getByTestId('cp-reorder-pane')).toBeVisible()
    await expect(page.getByTestId('cp-move').first()).toBeVisible({ timeout: 30_000 })
    expect(await page.getByTestId('cp-move').count()).toBeGreaterThan(0)
    await expect(page.getByTestId('cp-reorder-why')).toContainText('vpn-instance')
    await expect(page.getByTestId('cp-reorder-after')).toContainText('0')
    await expect(page.locator('[data-testid="cp-reorder-cols"] .rl.is-mv').first()).toBeVisible()
    // 采用：保存为修订
    await page.getByTestId('cp-adopt').click()
    await expect(page.getByTestId('cp-adopted')).toBeVisible()

    // 看对比：重排前后，移动识别为“移动”
    await page.getByTestId('cp-adopted-diff').click()
    await expect(page.getByTestId('cp-diff-pane')).toBeVisible()
    await expect(page.getByTestId('cp-diff-split')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByTestId('cp-diff-moves')).not.toHaveText('0')
    await expect(page.getByTestId('cp-mvtag').first()).toBeVisible()
    await page.getByTestId('cp-diff-mode').locator('[data-mode="unified"]').click()
    await expect(page.getByTestId('cp-diff-unified')).toBeVisible()
    await page.locator('label:has([data-testid="cp-diff-ignore"])').click()
    await expect(page.getByTestId('cp-diff-moves')).toHaveText('—')
    // 下载统一 diff
    const dl = page.waitForEvent('download')
    await page.getByTestId('cp-dl-diff').click()
    expect((await dl).suggestedFilename()).toMatch(/\.diff$/)
    await expectNoKeys(page)

    // 修订记录：新建 #1、重排前 #2（手动）、重排 #3；恢复到 #2
    await page.goBack()
    await page.goBack()
    await expect(page.getByTestId('cp-fn')).toBeVisible()
    await page.getByTestId('cp-revisions').click()
    await expect(page.getByTestId('cp-revisions-pane')).toBeVisible()
    await expect(page.getByTestId('cp-rev-3')).toContainText('按依赖重排')
    await page.getByTestId('cp-rev-2').click()
    await expect(page.getByTestId('cp-rev-preview')).toContainText('ip binding vpn-instance NEWVPN')
    await page.getByTestId('cp-rev-restore').click()
    await page.getByTestId('cp-rev-restore-ok').click()
    await expect(page.getByTestId('cp-rev-4')).toContainText('恢复')
    await expectNoKeys(page)

    // 回到工作区：编辑器是恢复后的内容（顺序错误又出现）
    await page.getByRole('button', { name: '回到工作区' }).click()
    await waitChecked(page)
    await expect(page.locator('[data-testid="cp-issue"][data-cat="order"]').first()).toBeVisible({ timeout: 30_000 })

    // 列表页显示项目与最近检查
    await page.getByTestId('nav-scripts').click()
    await expect(page.getByTestId('scripts-table')).toContainText('bind-vpn.txt')
    await expectNoKeys(page)
    expect(errors).toEqual([])
  } finally {
    await cleanup(request, projectId, deviceId)
  }
})
