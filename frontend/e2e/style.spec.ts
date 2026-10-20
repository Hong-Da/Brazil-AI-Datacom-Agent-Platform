import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { collectErrors, expectNoRawKeys, login, TOKEN } from './helpers'

// 0.2.1：显示风格（REQ-026）、关系图谱（REQ-027）、隐藏配置的区分（REQ-028）。

const H = { Authorization: `Bearer ${TOKEN}` }

async function devices(request: APIRequestContext): Promise<{ id: number; name: string; versions: number }[]> {
  return (await (await request.get('/api/v1/devices', { headers: H })).json()).data.devices
}
async function atn(request: APIRequestContext): Promise<number> {
  // 按设备名找 e2e_server.py 导入的华为 ATN 样本：其他用例（如 req031）会另外导入华为设备，不能按“排除法”取
  return (await devices(request)).find((d) => d.name === 'ORG-364464')!.id
}
async function style(page: Page, s: 'huawei' | 'cisco'): Promise<void> {
  const b = page.getByTestId('style-switch').locator(`[data-style="${s}"]`)
  await b.click()
  await expect(b).toHaveAttribute('aria-pressed', 'true')
}

test.beforeEach(async ({ page }) => {
  await login(page)
})

test('显示风格：设备配置图的节点名随风格变化，华为默认按视图层级、Cisco 按功能域', async ({ page, request }) => {
  const errors = collectErrors(page)
  const id = await atn(request)
  await page.goto(`/graph/${id}?node=${encodeURIComponent('vrf.instance[ABIS]')}`)
  const name = page.getByTestId('node-detail').getByTestId('detail-name')
  await expect(name).toHaveText('ip vpn-instance ABIS')
  await expect(name).toHaveAttribute('title', 'vrf.instance[ABIS]')
  await expect(page.getByTestId('org-switch').locator('[data-org="tree"]')).toHaveAttribute('aria-pressed', 'true')

  await style(page, 'cisco')
  await expect(name).toHaveText('vrf definition ABIS')
  await expect(page.getByTestId('org-switch').locator('[data-org="domain"]')).toHaveAttribute('aria-pressed', 'true')
  // 风格保存在浏览器里，刷新后仍是 Cisco
  await page.reload()
  await expect(page.getByTestId('node-detail').getByTestId('detail-name')).toHaveText('vrf definition ABIS')
  await style(page, 'huawei')
  await expect(page.getByTestId('node-detail').getByTestId('detail-name')).toHaveText('ip vpn-instance ABIS')
  await expectNoRawKeys(page)
  expect(errors).toEqual([])
})

test('显示风格：配置对比的差异列表随风格变化', async ({ page, request }) => {
  const asr = (await devices(request)).find((d) => d.versions >= 2)!
  await page.goto(`/compare?mode=versions&a=${asr.id}`)
  await page.getByTestId('run-compare').click()
  const list = page.getByTestId('diff-list')
  await expect(list).toBeVisible()
  await expect(list).toContainText('route-policy EXPORT-LO')
  await style(page, 'cisco')
  await expect(list).toContainText('route-map EXPORT-LO')
  await expect(list).not.toContainText('route-policy EXPORT-LO')
  await style(page, 'huawei')
})

test('关系图谱：出现圆点，能拖动，点击打开详情', async ({ page, request }) => {
  const errors = collectErrors(page)
  await page.goto(`/graph/${await atn(request)}`)
  await page.getByTestId('view-switch').locator('[data-view="force"]').click()
  const canvas = page.getByTestId('force-canvas')
  await expect(canvas).toBeVisible()
  await expect.poll(async () => Number(await canvas.getAttribute('data-nodes'))).toBeGreaterThan(20)
  await expect(canvas).toHaveAttribute('data-layouting', '0', { timeout: 30_000 })
  await expect(page.getByTestId('domain-legend')).toBeVisible()

  const box = (await canvas.boundingBox())!
  const handle = await canvas.evaluateHandle((el) => (el as unknown as { __cy: unknown }).__cy)
  // 取连接最多的对象圆点（跳过 M8-3 加的设备根节点），移到视野中央
  const p0 = await handle.evaluate((cy: any) => {
    const n = cy.nodes().filter((x: any) => !x.id().startsWith('__')).max((x: any) => x.degree()).ele
    cy.center(n)
    return { id: n.id(), ...n.renderedPosition(), model: { ...n.position() } }
  })
  await page.mouse.move(box.x + p0.x, box.y + p0.y)
  await page.mouse.down()
  await page.mouse.move(box.x + p0.x + 60, box.y + p0.y + 40, { steps: 8 })
  await page.mouse.up()
  const moved = await handle.evaluate((cy: any, id: string) => cy.getElementById(id).position(), p0.id)
  expect(Math.abs(moved.x - p0.model.x) + Math.abs(moved.y - p0.model.y)).toBeGreaterThan(10)

  // 点击圆点打开详情：先把它放大到视野中央，避免较挤的布局里相邻圆点压在上面
  const p1 = await handle.evaluate((cy: any, id: string) => {
    const n = cy.getElementById(id)
    cy.zoom({ level: Math.max(cy.zoom() * 2, 1.5), renderedPosition: n.renderedPosition() })
    cy.center(n)
    return n.renderedPosition()
  }, p0.id)
  await page.mouse.click(box.x + p1.x, box.y + p1.y)
  await expect(page.getByTestId('node-detail').getByTestId('detail-name')).toHaveAttribute('title', p0.id)
  await page.getByTestId('view-switch').locator('[data-view="tree"]').click()
  await expect(page.getByTestId('graph-canvas')).toBeVisible()
  expect(errors).toEqual([])
})

test('隐藏配置：显示默认配置开关生效，详情写明来自 Profile 的缺省值', async ({ page, request }) => {
  const id = await atn(request)
  const g = (await (await request.get(`/api/v1/devices/${id}/graph`, { headers: H })).json()).data
  type N = { id: string; origin: string; kind: string }
  const defs = (g.nodes as N[]).filter((n) => n.origin === 'default' && n.kind === 'attr')
  // 优先取接口以外的默认值（接口很多，可能被收进“还有 N 个”）
  const def = defs.find((n) => !n.id.startsWith('interface[')) ?? defs[0]
  expect(def, 'ATN 应有默认值节点').toBeTruthy()

  // 选中一个默认值节点（展开它的上级），树状图里默认值节点只在打开开关后出现（灰色虚线，样式类 s-default）
  await page.goto(`/graph/${id}?node=${encodeURIComponent(def.id)}`)
  const canvas = page.getByTestId('graph-canvas')
  const toggle = page.getByTestId('toggle-default')
  await expect(toggle).not.toBeChecked()
  await expect(page.getByTestId('hidden-legend')).toBeVisible()
  const handle = await canvas.evaluateHandle((el) => (el as unknown as { _cyreg: { cy: unknown } })._cyreg.cy)
  await expect.poll(() => handle.evaluate((cy: any) => cy.nodes().length)).toBeGreaterThan(1)
  expect(await handle.evaluate((cy: any) => cy.nodes('.s-default').length)).toBe(0)
  await toggle.check()
  await expect.poll(() => handle.evaluate((cy: any) => cy.nodes('.s-default').length)).toBeGreaterThan(0)
  // 关系图谱共用同一个开关，并记住选择
  await page.getByTestId('view-switch').locator('[data-view="force"]').click()
  await expect(page.getByTestId('toggle-default')).toBeChecked()
  await page.reload()
  await expect(page.getByTestId('toggle-default')).toBeChecked()
  await page.getByTestId('toggle-default').uncheck()
  await page.getByTestId('view-switch').locator('[data-view="tree"]').click()

  await page.goto(`/graph/${id}?node=${encodeURIComponent(def.id)}`)
  const note = page.getByTestId('node-detail').getByTestId('default-note')
  await expect(note).toContainText(g.profile)
  await expect(page.getByTestId('node-detail').locator('.hid-default')).toBeVisible()
})
