import { expect, test, type Page } from '@playwright/test'
import { collectErrors, login } from './helpers'

/**
 * M8-2 AI 建议框架的示范流程。
 * - playwright.m82.config.ts（假的 AI）：设备分析页 → AI 按钮生成设备摘要 → 代码填入的数字是实线小块 → 采纳 → 采纳记录里撤销；
 *   拓扑页 → 生成设备角色 → 编造设备的建议被拒绝（不能采纳）→ 全部采纳只采纳通过的 2 条 → 项目视图标注有 2 条。
 * - 主配置（没有 AI）：入口按钮显示“不可用”，点开是 REQ-040 的原因提示。
 */
async function atnId(page: Page): Promise<number> {
  const r = await page.request.get('/api/v1/devices')
  const devs = (await r.json()).data.devices as { id: number; name: string }[]
  return (devs.find((d) => /ATN/i.test(d.name)) ?? devs[0]).id
}

test('AI 建议：设备摘要采纳与撤销、拓扑角色批量采纳（未配置 AI 时入口说明原因）', async ({ page }) => {
  test.setTimeout(150_000)
  await login(page, 'zh-CN')
  const errors = collectErrors(page)
  const proj = ((await (await page.request.get('/api/v1/projects')).json()).data.mine as { slug: string }[])[0].slug
  const skills = (await (await page.request.get(`/api/v1/projects/${proj}/ai/suggestions/skills`)).json()).data
  const id = await atnId(page)
  await page.goto(`/analysis/${id}`)
  const entry = page.getByTestId('ai-entry')
  await expect(entry).toBeVisible()

  if (!skills.ai.configured) {
    await expect(entry).toHaveAttribute('data-off', 'true')
    await page.getByTestId('ai-entry-main').click()
    await expect(page.getByTestId('ai-entry-menu').locator('[data-ai-off]')).toBeVisible()
    expect(errors).toEqual([])
    return
  }

  // 设备摘要：运行 → 校验通过 → 采纳 → 撤销
  await page.getByTestId('ai-entry-main').click()
  const panel = page.getByTestId('ai-panel-device-summary')
  await expect(panel.getByTestId('ai-summary')).toBeVisible({ timeout: 60_000 })
  await expect(panel.getByTestId('ai-meta')).toContainText('fake-model')
  const card = panel.locator('[data-testid^="ai-sg-"][data-check]').first()
  await expect(card).toHaveAttribute('data-check', 'pass')
  await card.locator('.sg-h').click() // 通过的默认折叠，展开看正文
  await expect(card.getByTestId('ai-text-num')).toBeVisible() // 代码填入的数字（实线）
  await expect(card.getByTestId('ai-text-ref').first()).toBeVisible()
  await card.getByTestId('ai-sg-adopt').click()
  await expect(card).toHaveAttribute('data-status', 'adopted')
  await expect(panel.getByTestId('ai-log')).toBeVisible()
  await panel.getByTestId('ai-undo').first().click()
  await expect(card).toHaveAttribute('data-status', 'reverted')

  // 拓扑角色：编造的设备被拒绝；全部采纳只采纳通过的
  await page.goto('/topology')
  await page.getByTestId('ai-entry-main').click()
  const tp = page.getByTestId('ai-panel-topology-roles')
  await expect(tp.getByTestId('ai-summary')).toBeVisible({ timeout: 60_000 })
  const rejected = tp.locator('[data-check="reject"]')
  await expect(rejected).toHaveCount(1)
  await expect(rejected.locator('.sg-b')).toBeVisible() // 被拒绝的默认展开，显示原因
  await expect(rejected.getByTestId('ai-sg-adopt')).toHaveCount(0)
  await expect(rejected.locator('.aref.bad')).toHaveCount(1) // 不存在的对象打删除线
  await tp.getByTestId('ai-adopt-all').click()
  await expect(tp.locator('[data-status="adopted"]')).toHaveCount(2)
  const ann = (await (await page.request.get(`/api/v1/projects/${proj}/view-annotations`)).json()).data.items as { value: string; source: string }[]
  expect(ann.map((a) => a.value).sort()).toEqual(['access', 'pe'])
  expect(errors).toEqual([])
})
