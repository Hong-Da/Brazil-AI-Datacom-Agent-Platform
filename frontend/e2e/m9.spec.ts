import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test, type Page } from '@playwright/test'
import { collectErrors, login } from './helpers'

// M9-5（REQ-045）项目内的网络：在单独的项目 e2e-m9 里导入拓扑样本（knowledge/samples/topology）→ 只有默认网络时旧网址进默认网络
// → 新建网络 → 成员（从设备池添加、固定版本、自动加入规则）→ 切换器切换网络与“全部设备”汇总 → 拓扑“显示网络外的对端”（记住选择）
// → 建网建议采纳 → 删除网络。用例结束删除项目，不影响其他用例。

const SLUG = 'e2e-m9'
const TOPO = (f: string) => fileURLToPath(new URL(`../../knowledge/samples/topology/${f}`, import.meta.url))
const FILES = ['agg-01.cfg', 'agg-02.cfg', 'atn-a1.cfg', 'atn-a2.cfg', 'rr-01.cfg']

async function noRawNetKeys(page: Page): Promise<void> {
  const text = await page.locator('body').innerText()
  const raw = text.match(/\bnet\.[a-zA-Z][\w.]*\b/g)
  expect(raw ?? [], `未翻译的文案键：${raw?.join(', ')}`).toEqual([])
}

test('网络：新建、成员与规则、切换、全部设备汇总、网络外的对端、建网建议、删除', async ({ page }) => {
  test.setTimeout(240_000)
  await login(page)
  const errors = collectErrors(page)
  await page.request.delete(`/api/v1/projects/${SLUG}`)
  const created = await page.request.post('/api/v1/projects', { data: { name: 'M9 网络', slug: SLUG } })
  expect(created.ok(), await created.text()).toBeTruthy()
  try {
    for (const f of FILES) {
      const r = await page.request.post(`/api/v1/projects/${SLUG}/configs`, { multipart: { level: 'basic', files: { name: f, mimeType: 'text/plain', buffer: readFileSync(TOPO(f)) } } })
      expect(r.ok(), await r.text()).toBeTruthy()
    }

    // 只有默认网络：项目层的按网络页面（升级前的旧网址）直接进默认网络
    await page.goto(`/p/${SLUG}/scripts`)
    await expect(page).toHaveURL(new RegExp(`/p/${SLUG}/n/default/scripts$`))
    await expect(page.getByTestId('network-current')).toContainText('默认网络')
    await expect(page.getByTestId('net-scope')).toContainText('5 台设备')

    // 新建网络 → 进入成员页
    await page.goto(`/p/${SLUG}/networks`)
    await expect(page.getByTestId('net-overview')).toContainText('5')
    await page.getByTestId('new-network').click()
    const dlg = page.getByTestId('new-network-dialog')
    await dlg.getByTestId('new-name').fill('汇聚网')
    await dlg.getByTestId('new-slug').fill('agg')
    await dlg.getByTestId('new-create').click()
    await expect(page).toHaveURL(new RegExp(`/p/${SLUG}/n/agg/members`))
    await expect(page.getByTestId('members-msg')).toBeVisible()
    await expect(page.getByTestId('network-current')).toContainText('汇聚网')

    // 从设备池添加两台汇聚，固定在当前版本
    await page.getByTestId('add-members').click()
    const add = page.getByTestId('add-dialog')
    await add.getByTestId('pool-TOPO-AGG-01').locator('input[type=checkbox]').check()
    await add.getByTestId('pool-TOPO-AGG-02').locator('input[type=checkbox]').check()
    await add.getByTestId('add-go').click()
    const table = page.getByTestId('members-table')
    await expect(table.getByTestId('member-TOPO-AGG-01')).toBeVisible()
    await expect(table.locator('tbody tr')).toHaveCount(2)
    await table.getByTestId('member-TOPO-AGG-01').locator('input[type=checkbox]').check()
    await page.getByTestId('bulk-pin').click()
    await expect(page.getByTestId('members-msg')).toContainText('1')
    await expect(table.getByTestId('member-ver-TOPO-AGG-01')).toContainText('固定在')

    // 自动加入规则：预览命中，再添加
    await page.getByTestId('rule-pattern').fill('TOPO-RR-*')
    await expect(page.getByTestId('rule-preview')).toContainText('1')
    await page.getByTestId('rule-add').click()
    await expect(page.getByTestId('join-rules')).toContainText('TOPO-RR-*')
    await expect(table.locator('tbody tr')).toHaveCount(3) // 勾了“同时把现在命中的加进来”
    await noRawNetKeys(page)

    // 切换器：搜索并切到默认网络；Alt+N 打开，选“全部设备”看汇总
    await page.getByTestId('network-switcher-button').click()
    await page.getByTestId('network-switcher-search').fill('默认')
    await page.getByTestId('nsw-default').click()
    await expect(page).toHaveURL(new RegExp(`/p/${SLUG}/n/default/members$`))
    await page.keyboard.press('Alt+N')
    // 暗色主题：切换器弹层不是白底
    await page.emulateMedia({ colorScheme: 'dark' })
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await expect.poll(() => page.locator('.nw-pop').evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe('rgb(255, 255, 255)')
    await page.emulateMedia({ colorScheme: 'light' })
    await page.getByTestId('nsw-all').click()
    await expect(page).toHaveURL(new RegExp(`/p/${SLUG}/members$`))
    await expect(page.getByTestId('net-summary')).toBeVisible()
    await expect(page.getByTestId('sum-row-agg')).toContainText('3')
    await page.getByTestId('sum-open-agg').click()
    await expect(page).toHaveURL(new RegExp(`/p/${SLUG}/n/agg/members$`))

    // 拓扑：只画本网络；打开“显示网络外的对端”，画出到 ATN 的短线；刷新后仍记得
    await page.goto(`/p/${SLUG}/n/agg/topology`)
    const canvas = page.getByTestId('topo-canvas')
    await expect(canvas).not.toHaveAttribute('data-nodes', '0', { timeout: 60_000 })
    const tog = page.getByTestId('topo-outside-toggle')
    await expect(tog).not.toBeChecked()
    await tog.check()
    await expect(canvas).not.toHaveAttribute('data-outside', '0', { timeout: 60_000 })
    await page.reload()
    await expect(page.getByTestId('topo-outside-toggle')).toBeChecked()
    await expect(page.getByTestId('topo-canvas')).not.toHaveAttribute('data-outside', '0', { timeout: 60_000 })
    // 默认网络没有“网络外”
    await page.goto(`/p/${SLUG}/n/default/topology`)
    await expect(page.getByTestId('topo-canvas')).not.toHaveAttribute('data-nodes', '0', { timeout: 60_000 })
    await expect(page.getByTestId('topo-outside-toggle')).toHaveCount(0)
    await noRawNetKeys(page)

    // 建网建议：按设备名规则，采纳第一个可采纳的建议
    await page.goto(`/p/${SLUG}/networks/suggest`)
    await page.getByTestId('basis-name').click()
    const list = page.getByTestId('suggest-list')
    await expect(list).toBeVisible({ timeout: 60_000 })
    await list.locator('[data-testid^="sugg-adopt-"]').first().click()
    await expect(page.getByTestId('suggest-msg')).toContainText('1')
    await noRawNetKeys(page)

    // 网络列表：三个网络；删除汇聚网（输入名称确认）
    await page.goto(`/p/${SLUG}/networks`)
    const tree = page.getByTestId('net-tree')
    await expect(tree.locator('[data-testid^="net-row-"]')).toHaveCount(3)
    await expect(page.getByTestId('net-del-default')).toBeDisabled()
    await page.getByTestId('net-del-agg').click()
    const del = page.getByTestId('delete-dialog')
    await expect(del.getByTestId('delete-what')).toBeVisible()
    await expect(del.getByTestId('delete-go')).toBeDisabled()
    await del.getByTestId('delete-type').fill('汇聚网')
    await del.getByTestId('delete-go').click()
    await expect(page.getByTestId('net-msg')).toBeVisible()
    await expect(tree.locator('[data-testid^="net-row-"]')).toHaveCount(2)
    // 设备仍在项目里
    await page.goto(`/p/${SLUG}/devices`)
    await expect(page.getByTestId('devices-table').locator('[data-testid="device-link"]')).toHaveCount(5)
    await noRawNetKeys(page)
    expect(errors).toEqual([])
  } finally {
    await page.request.delete(`/api/v1/projects/${SLUG}`)
  }
})
