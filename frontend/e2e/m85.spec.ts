import { expect, test, type Page } from '@playwright/test'
import { collectErrors, login } from './helpers'

/**
 * M8-5 规范与合规、知识库构建、报告的 AI skill。
 * - playwright.m85.config.ts（假的本地模型）：配置检查页“规则”标签粘贴规范 → 规范转规则 → 一条通过（样本试跑有命中）、一条被拒绝 →
 *   采纳送审核队列；设备分析页脱敏复核（本地模型）→ 标出的描述通过、编造的客户名被拒绝 → 采纳进入项目的脱敏补充；
 *   报告摘要（接口）采纳后，导出的检查报告带 AI 摘要，取消勾选时不带。
 * - 主配置（没有 AI）：规范转规则的入口显示“不可用”。
 */
async function atnId(page: Page): Promise<number> {
  const r = await page.request.get('/api/v1/devices')
  const devs = (await r.json()).data.devices as { id: number; name: string }[]
  return (devs.find((d) => /ATN/i.test(d.name)) ?? devs[0]).id
}

test('AI 规范转规则、脱敏复核、报告摘要（未配置 AI 时入口说明原因）', async ({ page }) => {
  test.setTimeout(240_000)
  await login(page, 'zh-CN')
  const errors = collectErrors(page)
  const proj = ((await (await page.request.get('/api/v1/projects')).json()).data.mine as { slug: string }[])[0].slug
  const P = `/api/v1/projects/${proj}`
  const skills = (await (await page.request.get(`${P}/ai/suggestions/skills`)).json()).data

  await page.goto('/check#rules')
  const box = page.getByTestId('rule-draft')
  await expect(box).toBeVisible()
  if (!skills.ai.configured) {
    await expect(box.getByTestId('ai-entry')).toHaveAttribute('data-off', 'true')
    expect(errors).toEqual([])
    return
  }

  // 规范转规则：粘贴规范 → 运行 → 一条通过一条拒绝 → 采纳送审
  await box.getByTestId('rule-doc-paste').click()
  await box.getByTestId('rule-doc-text').fill('4.2.1 所有三层接口必须配置描述。\n\n4.4 用户侧端口应开启广播风暴抑制。')
  await box.getByTestId('rule-doc-use').click()
  await box.getByTestId('ai-entry-main').click()
  const rp = page.getByTestId('ai-panel-rule-draft')
  await expect(rp.getByTestId('ai-summary')).toBeVisible({ timeout: 90_000 })
  await expect(rp.locator('[data-check="reject"]')).toHaveCount(1)
  const ok = rp.locator('[data-check="pass"]').first()
  await ok.locator('.sg-h').click()
  await expect(ok.getByTestId('ai-kb-trial')).toBeVisible()
  await ok.getByTestId('ai-sg-adopt').click()
  await page.getByTestId('ai-confirm-seen').check()
  await page.getByTestId('ai-confirm-ok').click()
  await expect(ok).toHaveAttribute('data-status', 'adopted')
  await expect(page.getByTestId('rule-review-list')).toBeVisible()

  // 脱敏复核（本地模型）
  const id = await atnId(page)
  await page.goto(`/analysis/${id}?ai=sanitize`)
  const san = page.getByTestId('san-review')
  await expect(san).toBeVisible()
  await san.getByTestId('ai-entry-more').click() // 从菜单选择 skill（不依赖入口按钮的加载时机）
  await san.getByTestId('ai-entry-sanitize-review').click()
  const sp = page.getByTestId('ai-panel-sanitize-review')
  await expect(sp.getByTestId('ai-summary')).toBeVisible({ timeout: 90_000 })
  await expect(sp.locator('[data-check="reject"]')).toHaveCount(1)
  const sok = sp.locator('[data-check="pass"]').first()
  await sok.getByTestId('ai-sg-adopt').click()
  await expect(sok).toHaveAttribute('data-status', 'adopted')
  await expect(san.getByTestId('san-redact-item')).toHaveCount(1)

  // 报告摘要：接口运行与采纳，导出的报告带 / 不带 AI 摘要
  const run = await page.request.post(`${P}/ai/suggestions/run`, { data: { skill: 'report-summary', params: { kind: 'check', device_id: id }, wait: true } })
  expect(run.ok(), await run.text()).toBeTruthy()
  const items = (await (await page.request.get(`${P}/ai/suggestions?skill=report-summary&check=pass`)).json()).data.items as { id: number }[]
  expect(items.length).toBe(2)
  for (const it of items) expect((await page.request.post(`${P}/ai/suggestions/${it.id}/adopt`, { data: {} })).ok()).toBeTruthy()
  const body = { kind: 'check', lang: 'zh-CN', format: 'html', check: { device_id: id } }
  expect(await (await page.request.post(`${P}/reports`, { data: body })).text()).toContain('class="ai-summary"')
  expect(await (await page.request.post(`${P}/reports`, { data: { ...body, include_ai_summary: false } })).text()).not.toContain('class="ai-summary"')
  expect(errors).toEqual([])
})
