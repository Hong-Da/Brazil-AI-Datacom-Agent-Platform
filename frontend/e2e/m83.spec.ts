import { expect, test, type Page } from '@playwright/test'
import { collectErrors, login } from './helpers'

/**
 * M8-3：REQ-042 设备图标与日常分析组的 AI skill。
 * - 两种配置都跑：设备列表的设备图标、设备摘要入口与交接文档链接；拓扑图的手工标注（来源 user）；图标风格切换（个人偏好）。
 * - playwright.m83.config.ts（假的 AI）：拓扑整理（编造设备与连不上的推测对端被拒绝，全部采纳只采纳通过的）、
 *   版本历史的变化解读（编造的差异条目被拒绝，覆盖条列出没被解释的差异）。主配置（没有 AI）下入口显示“不可用”。
 */
async function projectSlug(page: Page): Promise<string> {
  return ((await (await page.request.get('/api/v1/projects')).json()).data.mine as { slug: string }[])[0].slug
}
async function devices(page: Page): Promise<{ id: number; name: string; versions: number }[]> {
  return (await (await page.request.get('/api/v1/devices')).json()).data.devices
}
async function tapNode(page: Page, id: string): Promise<void> {
  await page.evaluate((nid) => {
    const el = document.querySelector('[data-testid="topo-canvas"]') as unknown as { __cy?: { getElementById: (x: string) => { emit: (e: string) => void } } }
    el.__cy?.getElementById(nid).emit('tap')
  }, id)
}

test('设备图标、手工标注与图标风格（不需要 AI）', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page, 'zh-CN')
  const errors = collectErrors(page)
  const proj = await projectSlug(page)
  const devs = await devices(page)
  const agg = devs.find((d) => d.name === 'TOPO-AGG-01')
  // 设备列表：名称前有设备图标；设备摘要入口打开分析页的摘要面板，并有中文 / English 交接文档
  await page.goto('/devices')
  await expect(page.getByTestId('devicon').first()).toBeVisible()
  const atn = devs.find((d) => /ATN/i.test(d.name)) ?? devs[0]
  await page.getByTestId(`dev-summary-${atn.id}`).click()
  await expect(page).toHaveURL(/analysis\/\d+.*ai=summary/)
  await expect(page.getByTestId('handover-zh')).toBeVisible()
  await expect(page.getByTestId('handover-en')).toBeVisible()
  // 拓扑：选中设备 → 手工改角色与分组 → 视图标注来源 user
  await page.goto('/topology')
  await expect(page.getByTestId('topo-canvas')).toBeVisible({ timeout: 60_000 })
  if (agg) { // 拓扑样本网络只在 m83 配置里导入（主配置的样本设备之间没有链路，图上不画）
    await expect(page.getByTestId('topo-canvas')).toHaveAttribute('data-nodes', /[1-9]/, { timeout: 60_000 })
    await tapNode(page, agg.name)
    await expect(page.getByTestId('topo-role-edit')).toBeVisible()
    await page.getByTestId('topo-role-select').selectOption('core')
    await page.getByTestId('topo-group-input').fill('Central')
    await page.getByTestId('topo-anno-save').click()
    await expect(page.getByTestId('topo-role-src')).toHaveClass(/s-user/)
    const ann = (await (await page.request.get(`/api/v1/projects/${proj}/view-annotations`)).json()).data.items as { target: string; key: string; value: string; source: string }[]
    expect(ann.filter((a) => a.target === String(agg.id)).map((a) => `${a.key}=${a.value}:${a.source}`).sort()).toEqual(['group=Central:user', 'role=core:user'])
  }
  // 图标风格：三套可切换，存为个人偏好（默认 B 几何徽章）
  expect(await page.evaluate(() => localStorage.getItem('lmesh-icon-set'))).toBeNull()
  await page.getByTestId('icon-set-line').first().click()
  expect(await page.evaluate(() => localStorage.getItem('lmesh-icon-set'))).toBe('line')
  await page.getByTestId('icon-set-geo').first().click()
  expect(errors).toEqual([])
})

test('日常分析的 AI：拓扑整理与变化解读（未配置 AI 时入口说明原因）', async ({ page }) => {
  test.setTimeout(180_000)
  await login(page, 'zh-CN')
  const errors = collectErrors(page)
  const proj = await projectSlug(page)
  const skills = (await (await page.request.get(`/api/v1/projects/${proj}/ai/suggestions/skills`)).json()).data
  await page.goto('/topology')
  await expect(page.getByTestId('topo-canvas')).toBeVisible({ timeout: 60_000 })
  const entry = page.getByTestId('ai-entry').first()
  await expect(entry).toBeVisible()
  if (!skills.ai.configured) {
    await expect(entry).toHaveAttribute('data-off', 'true')
    expect(errors).toEqual([])
    return
  }
  // 拓扑整理：编造的设备 d9 与已有链路的推测对端被拒绝；全部采纳只采纳通过的（角色、分组）
  await page.getByTestId('ai-entry-main').first().click()
  const tp = page.getByTestId('ai-panel-topology-roles')
  await expect(tp.getByTestId('ai-summary')).toBeVisible({ timeout: 60_000 })
  await expect(tp.locator('[data-check="reject"]')).toHaveCount(2)
  const passed = await tp.locator('[data-check="pass"]').count() // d1 若已被手工标注，角色建议是 warn（逐条采纳）
  expect(passed).toBeGreaterThan(0)
  await tp.getByTestId('ai-adopt-all').click()
  await expect(tp.locator('[data-status="adopted"]')).toHaveCount(passed)
  const ann = (await (await page.request.get(`/api/v1/projects/${proj}/view-annotations`)).json()).data.items as { value: string; source: string }[]
  expect(ann.filter((a) => a.source === 'ai').length).toBe(passed)

  // 版本历史：变化解读；编造的差异条目被拒绝，覆盖条列出没被解释的差异
  const pe = (await devices(page)).find((d) => d.versions > 1)
  expect(pe).toBeTruthy()
  await page.goto(`/history/${pe!.id}`)
  const hist = page.getByTestId('hist-meta')
  await expect(hist).toBeVisible({ timeout: 30_000 })
  await page.getByTestId('ai-entry-main').first().click()
  const hp = page.getByTestId('ai-panel-diff-explain')
  await expect(hp.getByTestId('ai-summary')).toBeVisible({ timeout: 60_000 })
  await expect(hp.locator('[data-check="reject"]')).toHaveCount(1)
  await expect(page.getByTestId('ai-cov')).toBeVisible()
  expect(errors).toEqual([])
})
