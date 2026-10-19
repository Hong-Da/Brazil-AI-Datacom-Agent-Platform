import { expect, test, type Page } from '@playwright/test'
import { collectErrors, expectNoRawKeys, login } from './helpers'

/** 设备配置分析（REQ-034）：打开分析页 → 结构化脚本点引用跳到定义 → TCP/IP 视图选中对象 → 关系视图联动高亮 → 摘要跳转。 */

async function deviceId(page: Page, prefix: string): Promise<number> {
  const r = await page.request.get('/api/v1/devices')
  const devs = (await r.json()).data.devices as { id: number; name: string }[]
  return devs.find((d) => d.name.startsWith(prefix))!.id
}

/** 关系图谱（cytoscape）中选中的圆点。 */
async function forceSelected(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const el = document.querySelector('[data-testid="force-canvas"]') as unknown as { __cy?: { nodes: (s: string) => { map: (f: (n: { id: () => string }) => string) => string[] } } }
    return el?.__cy ? el.__cy.nodes('.is-sel').map((n) => n.id()) : []
  })
}

test('设备配置分析：引用跳转、TCP/IP 选中、关系视图联动', async ({ page }) => {
  await login(page, 'zh-CN')
  const errors = collectErrors(page)
  // 从设备列表进入
  await page.goto('/devices')
  const row = page.locator('tr', { hasText: 'PE-ASR920-01' }).first()
  await row.getByTestId('device-analysis-link').click()
  await expect(page).toHaveURL(/\/analysis\/\d+/)
  const script = page.getByTestId('script')
  await expect(script.locator('.r').first()).toBeVisible({ timeout: 60_000 })
  await expectNoRawKeys(page)

  // 结构化脚本：点 VRF 引用 → 选中 VRF、跳到定义行（高亮），右侧列出全部引用处
  // 虚拟滚动：先滚到引用所在的行附近（第 75 行），它才会被渲染
  await script.evaluate((el) => { el.scrollTop = 60 * 20 })
  const ref = script.locator('.rf[data-ref="vrf.instance[RAN-2G]"]').first()
  await ref.click()
  await expect(page.getByTestId('sel-label')).toContainText('RAN-2G')
  await expect(page.getByTestId('sel-def')).toContainText('23')
  await expect(script.locator('.r.is-hl[data-ln="23"]')).toBeVisible()
  await expect(page.getByTestId('sel-refs').locator('button')).toHaveCount(2)
  await expect(page.getByTestId('sel-layer')).toContainText('网络层')

  // TCP/IP 模型：同一个对象在网络层被选中，跨层依赖的对端加描边
  await page.locator('[data-view="tcpip"]').click()
  await expect(page.getByTestId('tcpip-view')).toBeVisible()
  const chip = page.locator('[data-testid="tcp-chip"].is-sel')
  await expect(chip).toHaveCount(1)
  await expect(chip).toContainText('RAN-2G')
  await expect(page.locator('[data-band="network"] [data-testid="tcp-chip"].is-sel')).toHaveCount(1)
  // 改选聚合口（数据链路层）：它的 IPv4 地址在网络层，是跨层依赖，对端加描边，右侧列出
  await page.locator('[data-band="datalink"] [data-testid="tcp-chip"]', { hasText: 'Port-channel1' }).first().click()
  await expect(page.getByTestId('sel-layer')).toContainText('数据链路层')
  await expect(page.locator('[data-band="network"] [data-testid="tcp-chip"].is-rel').first()).toBeVisible()
  await expect(page.getByTestId('sel-cross').locator('button').first()).toBeVisible()
  // 在 TCP/IP 视图里改选 BGP 对等体组（传输层）
  const peerGroup = page.locator('[data-band="transport"] [data-testid="tcp-chip"]', { hasText: 'RR' }).first()
  await peerGroup.click()
  await expect(page.getByTestId('sel-layer')).toContainText('传输层')

  // 配置关系：按层分带，选中的圆点同步
  await page.locator('[data-view="relation"]').click()
  await page.locator('[data-testid="rel-layout"] [data-layout="bands"]').click()
  await expect(page.getByTestId('force-canvas')).toHaveAttribute('data-layouting', '0', { timeout: 30_000 })
  await expect.poll(() => forceSelected(page)).toEqual([expect.stringContaining('peer_group[RR]')])
  // 在关系图上点结构化脚本，回到脚本时定位到选中对象的行
  await page.locator('[data-view="script"]').click()
  await expect(script.locator('.r.is-hl').first()).toBeVisible()

  // 分析摘要：六格齐全，点检查发现跳回脚本
  await page.locator('[data-view="summary"]').click()
  await expect(page.getByTestId('tile-baseline')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('tile-objects')).toContainText(/\d+/)
  const finding = page.getByTestId('finding').first()
  if (await finding.count()) {
    await finding.click()
    await expect(page.locator('.an-tabs [data-view="script"]')).toHaveAttribute('aria-selected', 'true')
    await expect(script.locator('.r.is-flash, .r.is-hl').first()).toBeVisible()
  }
  expect(errors).toEqual([])
})

test('设备配置分析：大配置虚拟滚动、Cisco 叫法、暗色主题', async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem('lmesh-theme', 'dark') })
  await login(page, 'en')
  const errors = collectErrors(page)
  const id = await deviceId(page, 'ORG-')
  await page.goto(`/analysis/${id}`)
  const script = page.getByTestId('script')
  await expect(script.locator('.r').first()).toBeVisible({ timeout: 90_000 })
  // 现网 ATN 约 2266 行：只渲染滚动窗口内的行
  expect(Number(await script.getAttribute('data-rows'))).toBeGreaterThan(2000)
  expect(await script.locator('.r').count()).toBeLessThan(150)
  await script.evaluate((el) => { el.scrollTop = el.scrollHeight })
  await expect(script.locator('.r[data-ln="2267"]')).toBeVisible()
  // 显示默认配置：默认值行插入
  await page.getByTestId('script-defaults').check()
  expect(Number(await script.getAttribute('data-rows'))).toBeGreaterThan(2267)
  // 显示风格：选中对象的命令写法随华为 / Cisco 切换
  await page.getByTestId('script-defaults').uncheck()
  await script.evaluate((el) => { el.scrollTop = 0 })
  const acl = script.locator('.rf[data-ref^="acl.instance["]').first()
  await acl.click()
  await expect(page.getByTestId('sel-label')).toContainText('NTP')
  const huawei = (await page.getByTestId('sel-label').innerText()).trim()
  await page.getByTestId('style-switch').locator('[data-style="cisco"]').click()
  await expect.poll(async () => (await page.getByTestId('sel-label').innerText()).trim()).not.toBe(huawei)
  await page.locator('[data-view="tree"]').click()
  await expect(page.getByTestId('analysis-tree')).toBeVisible()
  await page.getByTestId('style-switch').locator('[data-style="huawei"]').click()
  await page.locator('[data-view="tcpip"]').click()
  await expect(page.locator('[data-band="application"] [data-testid="tcp-chip"]').first()).toBeVisible()
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)
  expect(bg).not.toBe('rgb(255, 255, 255)')
  await page.locator('[data-view="summary"]').click()
  await expect(page.getByTestId('tile-defaults')).toBeVisible({ timeout: 60_000 })
  expect(errors).toEqual([])
})

test('设备配置分析：TCP/IP 视图合并相似（评审修改）', async ({ page }) => {
  await login(page, 'zh-CN')
  const errors = collectErrors(page)
  const id = await deviceId(page, 'ORG-')
  await page.goto(`/analysis/${id}?view=tcpip`)
  await expect(page.getByTestId('tcpip-view')).toBeVisible({ timeout: 90_000 })
  // 默认合并：大配置里同类接口等合并成范围格子
  await expect(page.getByTestId('tcp-merge')).toBeChecked()
  const merged = page.getByTestId('tcp-merged')
  await expect(merged.first()).toBeVisible()
  const mergedCount = await merged.count()
  const chipsOn = await page.getByTestId('tcp-chip').count()
  // 点开组逐个查看，选中其中一个成员，收起后组仍显示为选中
  const first = merged.first()
  const n = Number(await first.locator('.n').innerText())
  expect(n).toBeGreaterThanOrEqual(3)
  await first.click()
  const open = page.getByTestId('tcp-merged-open').first()
  await expect(open.getByTestId('tcp-chip')).toHaveCount(n)
  await open.getByTestId('tcp-chip').nth(1).click()
  await expect(open.locator('[data-testid="tcp-chip"].is-sel')).toHaveCount(1)
  await open.getByTestId('tcp-merged-fold').click()
  await expect(page.locator('[data-testid="tcp-merged"].is-sel')).toHaveCount(1)
  await expect(page.getByTestId('tcp-merged')).toHaveCount(mergedCount)
  // 关闭合并：逐个显示，选中的格子还在
  await page.getByTestId('tcpip-view').locator('.tcp-tools label').click() // 开关的 input 被样式隐藏，点标签
  await expect(page.getByTestId('tcp-merged')).toHaveCount(0)
  await expect(page.locator('[data-testid="tcp-chip"].is-sel')).toHaveCount(1)
  expect(await page.getByTestId('tcp-chip').count()).toBeGreaterThan(chipsOn)
  // 开关记在浏览器里：刷新后保持关闭
  await page.reload()
  await expect(page.getByTestId('tcpip-view')).toBeVisible({ timeout: 90_000 })
  await expect(page.getByTestId('tcp-merge')).not.toBeChecked()
  expect(errors).toEqual([])
})
