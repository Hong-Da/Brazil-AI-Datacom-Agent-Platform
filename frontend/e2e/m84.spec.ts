import { expect, test, type Page } from '@playwright/test'
import { collectErrors, login } from './helpers'

/**
 * M8-4 变更与割接组的 AI skill（预览 DevelopDocs/ui-preview/M8/change.html）。
 * - playwright.m84.config.ts（假的 AI，e2e/m84_server.py）：增量变更页写一句话 → 生成目标图改动 → 编造对象的被拒绝 →
 *   采纳（二次确认）→ 代码生成的变更脚本里有紫色的 AI 行、模拟执行通过；割接迁移页 → 方案起草 → 写出命令的一节被拒绝 →
 *   采纳概述后方案里显示“已采纳”；配置翻译页 → 未支持项 → 采纳“无对应”后重新翻译，表里标出。
 * - 主配置（没有 AI）：三处入口都在，按钮显示“不可用”。
 */
const TO = 'cisco-iosxe-asr920-17.15'

async function atnId(page: Page): Promise<number> {
  const devs = (await (await page.request.get('/api/v1/devices')).json()).data.devices as { id: number; name: string; profile: string }[]
  return (devs.find((d) => /ATN/i.test(d.name) && /huawei/.test(d.profile)) ?? devs[0]).id
}

async function adoptFirstPass(page: Page, panel: ReturnType<Page['getByTestId']>, confirm: boolean): Promise<void> {
  const card = panel.locator('[data-testid^="ai-sg-"][data-check="pass"]').first()
  await card.getByTestId('ai-sg-adopt').click()
  if (confirm) {
    await page.getByTestId('ai-confirm-seen').check()
    await page.getByTestId('ai-confirm-ok').click()
  }
  await expect(card).toHaveAttribute('data-status', 'adopted', { timeout: 60_000 })
}

test('变更与割接：意图转脚本、割接方案、翻译未支持项（未配置 AI 时入口说明原因）', async ({ page }) => {
  test.setTimeout(240_000)
  await login(page, 'zh-CN')
  const errors = collectErrors(page)
  const proj = ((await (await page.request.get('/api/v1/projects')).json()).data.mine as { slug: string }[])[0].slug
  const skills = (await (await page.request.get(`/api/v1/projects/${proj}/ai/suggestions/skills`)).json()).data
  const id = await atnId(page)

  // ---------- 增量变更：变更意图转脚本
  await page.goto(`/change?device=${id}`)
  const intent = page.getByTestId('ai-intent')
  await expect(intent).toBeVisible()
  await expect(intent.getByTestId('ai-intent-flow').locator('[data-cur="true"]')).toHaveCount(1)
  if (!skills.ai.configured) {
    await expect(intent.getByTestId('ai-entry')).toHaveAttribute('data-off', 'true')
    await page.goto(`/translate?device=${id}&to=${TO}`)
    await page.getByTestId('tr-run').click()
    await expect(page.getByTestId('ai-gap')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('ai-gap').getByTestId('ai-entry')).toHaveAttribute('data-off', 'true')
    expect(errors).toEqual([])
    return
  }
  await intent.getByTestId('ai-intent-text').fill('把第一个物理接口的描述改为 AI-E2E-DESC')
  await intent.getByTestId('ai-entry-main').click()
  const ip = page.getByTestId('ai-panel-intent-script')
  await expect(ip.getByTestId('ai-summary')).toBeVisible({ timeout: 90_000 })
  await expect(ip.locator('[data-check="reject"]')).toHaveCount(1)
  await expect(ip.locator('[data-check="reject"]').getByTestId('ai-sg-adopt')).toHaveCount(0)
  await expect(intent.getByTestId('ai-intent-script')).toContainText('采纳右侧')
  await adoptFirstPass(page, ip, true)
  const code = intent.getByTestId('ai-intent-code')
  await expect(code.locator('[data-k="ai"]')).toHaveCount(1, { timeout: 60_000 })
  await expect(code.locator('[data-k="ai"]')).toContainText('AI-E2E-DESC')
  await expect(intent.getByTestId('ai-intent-sim')).toHaveClass(/pass/)
  await intent.getByTestId('ai-intent-rb').click()
  await expect(code).not.toContainText('AI-E2E-DESC')

  // ---------- 割接迁移：割接方案文档
  await page.goto(`/migration?device=${id}&to=${TO}&run=1`)
  await page.getByTestId('mig-step-cut').click({ timeout: 90_000 })
  const cut = page.getByTestId('ai-cutover')
  await expect(cut).toBeVisible()
  await cut.getByTestId('ai-entry-main').click()
  const cp = page.getByTestId('ai-panel-cutover-plan')
  await expect(cp.getByTestId('ai-summary')).toBeVisible({ timeout: 90_000 })
  await expect(cp.locator('[data-check="reject"]')).toHaveCount(1)
  const doc = cut.getByTestId('ai-cutover-doc')
  await expect(doc.locator('[data-section="overview"]')).toHaveAttribute('data-state', 'pending')
  await adoptFirstPass(page, cp, false)
  await expect(doc.locator('[data-section="overview"]')).toHaveAttribute('data-state', 'adopted')
  await expect(doc.locator('[data-section="rollback"]')).toHaveAttribute('data-state', 'missing')
  await cut.getByTestId('ai-cutover-en').click()
  await expect(doc).toContainText('Replace ')

  // ---------- 配置翻译：未支持项
  await page.goto(`/translate?device=${id}&to=${TO}`)
  await page.getByTestId('tr-run').click()
  const gap = page.getByTestId('ai-gap')
  await expect(gap).toBeVisible({ timeout: 60_000 })
  await gap.getByTestId('ai-entry-main').click()
  const gp = page.getByTestId('ai-panel-translate-gap')
  await expect(gp.getByTestId('ai-summary')).toBeVisible({ timeout: 90_000 })
  await expect(gp.locator('[data-check="reject"]')).toHaveCount(1)
  await adoptFirstPass(page, gp, false)
  await expect(gap.getByTestId('ai-gap-table').locator('.dst')).toHaveCount(1, { timeout: 60_000 })
  expect(errors).toEqual([])
})
