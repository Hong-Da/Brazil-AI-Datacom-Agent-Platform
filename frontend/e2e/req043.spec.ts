import { readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test, type Page } from '@playwright/test'
import { collectErrors, login } from './helpers'

/**
 * 视图全屏（REQ-043）：进入全屏 → 在全屏里操作（缩放、选中、侧栏）→ 退出后缩放、选中、滚动位置保持。
 * 拓扑页走浏览器全屏（无头浏览器可能拒绝，此时自动退回页面内最大化，两种都接受）；
 * 设备分析页用 localStorage lmesh-fs=max 强制页面内最大化。
 */

const TOPO_DIR = fileURLToPath(new URL('../../knowledge/samples/topology/', import.meta.url))
const TOPO_FILES = readdirSync(TOPO_DIR).filter((f) => f.endsWith('.cfg')).map((f) => TOPO_DIR + f)

type Cy = { zoom: () => number; width: () => number; nodes: () => { map: (f: (n: { id: () => string; renderedPosition: () => { x: number; y: number } }) => unknown) => unknown[] } }

async function cyInfo(page: Page, testid: string): Promise<{ zoom: number; width: number; box: number; nodes: { id: string; x: number; y: number }[] }> {
  return page.evaluate((tid) => {
    const el = document.querySelector(`[data-testid="${tid}"]`) as HTMLElement & { __cy?: Cy }
    const cy = el.__cy!
    const nodes = cy.nodes().map((n) => ({ id: n.id(), ...n.renderedPosition() })) as { id: string; x: number; y: number }[]
    return { zoom: cy.zoom(), width: cy.width(), box: el.clientWidth, nodes }
  }, testid)
}

test('拓扑：F 进入全屏，缩放与选中设备后退出，状态保持', async ({ page }) => {
  await login(page)
  const errors = collectErrors(page)
  await page.goto('/topology')
  await page.getByTestId('topo-pick').click()
  await page.getByTestId('topo-include').uncheck()
  await page.getByTestId('topo-pick').click()
  await page.getByTestId('topo-upload').setInputFiles(TOPO_FILES)
  await page.getByTestId('topo-run').click()
  await expect(page.getByTestId('topo-canvas')).toHaveAttribute('data-nodes', '5', { timeout: 60_000 })

  const pane = page.getByTestId('topo-fs')
  const btn = pane.getByTestId('fs-btn')
  await expect(btn).toHaveAttribute('title', /F/)
  await expect(btn.locator('kbd')).toHaveText('F')
  const before = await cyInfo(page, 'topo-canvas')

  // F 键进入（焦点不在输入框上）
  await page.locator('body').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('f')
  await expect(pane).toHaveAttribute('data-fs', /native|max/)
  await expect(btn).toHaveAttribute('aria-pressed', 'true')
  const vp = page.viewportSize()!
  await expect.poll(async () => (await pane.boundingBox())?.width ?? 0).toBeGreaterThanOrEqual(vp.width - 2)
  // 图形组件跟随容器重算尺寸
  await expect.poll(async () => { const i = await cyInfo(page, 'topo-canvas'); return Math.abs(i.width - i.box) <= 2 && i.width > before.width }).toBe(true)

  // 在全屏里操作：滚轮缩放，点一台设备打开侧栏
  const canvas = page.getByTestId('topo-canvas')
  const cb = (await canvas.boundingBox())!
  const z0 = (await cyInfo(page, 'topo-canvas')).zoom
  await page.mouse.move(cb.x + cb.width / 2, cb.y + cb.height / 2)
  // 缩小（放大可能已到上限）
  await page.mouse.wheel(0, 300)
  await expect.poll(async () => (await cyInfo(page, 'topo-canvas')).zoom).toBeLessThan(z0)
  const inFs = await cyInfo(page, 'topo-canvas')
  const node = inFs.nodes.find((n) => n.x > 20 && n.y > 20 && n.x < cb.width - 20 && n.y < cb.height - 20)!
  await page.mouse.click(cb.x + node.x, cb.y + node.y)
  await expect(page.getByTestId('topo-dev')).toBeVisible()
  await expect(page.getByTestId('topo-side')).toBeInViewport()
  const zoomFs = (await cyInfo(page, 'topo-canvas')).zoom

  // 按钮退出
  await btn.click()
  await expect(pane).toHaveAttribute('data-fs', 'off')
  await expect(btn.locator('kbd')).toHaveText('F')
  await expect(page.getByTestId('topo-dev')).toBeVisible()
  await expect(page.getByTestId('topo-side')).toContainText(node.id)
  expect((await cyInfo(page, 'topo-canvas')).zoom).toBeCloseTo(zoomFs, 5)
  await expect.poll(async () => { const i = await cyInfo(page, 'topo-canvas'); return Math.abs(i.width - i.box) <= 2 }).toBe(true)
  expect(errors).toEqual([])
})

test('设备分析：页面内最大化，全屏里选中引用、切页签，Esc 退出后选中与滚动保持', async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem('lmesh-fs', 'max') })
  await login(page)
  const errors = collectErrors(page)
  const r = await page.request.get('/api/v1/devices')
  const id = ((await r.json()).data.devices as { id: number; name: string }[]).find((d) => d.name.startsWith('PE-ASR920-01'))!.id
  await page.goto(`/analysis/${id}`)
  const script = page.getByTestId('script')
  await expect(script.locator('.r').first()).toBeVisible({ timeout: 60_000 })

  const pane = page.getByTestId('analysis-fs')
  await pane.getByTestId('fs-btn').click()
  await expect(pane).toHaveAttribute('data-fs', 'max')
  await expect(page.getByTestId('fs-hint')).toContainText('页面内最大化')
  const vp = page.viewportSize()!
  const box = (await pane.boundingBox())!
  expect(box.x).toBe(0)
  expect(box.y).toBe(0)
  expect(Math.round(box.width)).toBe(vp.width)
  expect(Math.round(box.height)).toBe(vp.height)
  // 导航与顶栏被盖住：全屏区域在最上层
  expect(await page.evaluate(() => (document.elementFromPoint(5, 5) as HTMLElement).closest('[data-testid="analysis-fs"]') !== null)).toBe(true)

  // 全屏里：虚拟滚动区域变高，滚到引用处点击，右侧选中面板显示
  await expect.poll(() => script.evaluate((el) => el.clientHeight)).toBeGreaterThan(600)
  await script.evaluate((el) => { el.scrollTop = 60 * 20 })
  await script.locator('.rf[data-ref="vrf.instance[RAN-2G]"]').first().click()
  await expect(page.getByTestId('sel-label')).toContainText('RAN-2G')
  await expect(page.getByTestId('selection-panel')).toBeInViewport()
  // 页签在全屏里也能切换
  await page.locator('[data-view="tcpip"]').click()
  await expect(page.getByTestId('tcpip-view')).toBeVisible()
  await expect(page.locator('[data-testid="tcp-chip"].is-sel')).toHaveCount(1)
  await page.locator('[data-view="script"]').click()
  await expect(script.locator('.r.is-hl').first()).toBeVisible()
  // 在全屏里滚到底
  await script.evaluate((el) => { el.scrollTop = el.scrollHeight })
  await expect.poll(() => script.evaluate((el) => el.scrollTop)).toBeGreaterThan(50)
  const top = await script.evaluate((el) => el.scrollTop)

  // Esc 退出：选中保持，滚动位置不变
  await page.keyboard.press('Escape')
  await expect(pane).toHaveAttribute('data-fs', 'off')
  await expect(page.getByTestId('sel-label')).toContainText('RAN-2G')
  await expect.poll(async () => Math.abs((await script.evaluate((el) => el.scrollTop)) - top)).toBeLessThan(2)

  // 再按 F 进入、F 退出
  await page.keyboard.press('f')
  await expect(pane).toHaveAttribute('data-fs', 'max')
  await page.keyboard.press('f')
  await expect(pane).toHaveAttribute('data-fs', 'off')
  expect(errors).toEqual([])
})
