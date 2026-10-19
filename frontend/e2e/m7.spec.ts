import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { collectErrors, expectNoRawKeys, login, TOKEN } from './helpers'

// M7-5：Nokia 7750 SR（Classic CLI）设备在检查、配置图（Nokia 显示风格、按配置上下文分组）、翻译页的显示。
// 样本是合成配置（knowledge/samples/nokia-sros-classic-synthetic/），不是真实设备配置。

const H = { Authorization: `Bearer ${TOKEN}` }
const SAMPLE = fileURLToPath(new URL('../../knowledge/samples/nokia-sros-classic-synthetic/classic-pe-services.cfg', import.meta.url))
const NAME = 'classic-pe-services'

/** 导入 Nokia 样本；已经导入过（重复运行）时直接复用。 */
async function nokiaDevice(request: APIRequestContext): Promise<number> {
  const find = async () => ((await (await request.get('/api/v1/devices', { headers: H })).json()).data.devices as { id: number; name: string }[]).find((d) => d.name === NAME)
  let d = await find()
  if (!d) {
    const r = await request.post('/api/v1/configs', {
      headers: H,
      multipart: { files: { name: `${NAME}.cfg`, mimeType: 'text/plain', buffer: readFileSync(SAMPLE) } },
    })
    expect(r.ok(), await r.text()).toBeTruthy()
    d = await find()
  }
  expect(d, '应导入 Nokia 样本').toBeTruthy()
  return d!.id
}

async function style(page: Page, s: 'huawei' | 'cisco' | 'nokia'): Promise<void> {
  const b = page.getByTestId('style-switch').locator(`[data-style="${s}"]`)
  await b.click()
  await expect(b).toHaveAttribute('aria-pressed', 'true')
}

/** 树状图里画出来的节点名（GraphCanvas 在容器上留了 cytoscape 实例）。 */
async function treeLabels(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const el = document.querySelector('[data-testid="graph-canvas"]') as unknown as { __cy?: { nodes: () => { map: (f: (n: { data: (k: string) => string }) => string) => string[] } } }
    return el?.__cy ? el.__cy.nodes().map((n) => String(n.data('label'))) : []
  })
}

test.beforeEach(async ({ page }) => {
  await login(page)
})

test('Nokia：检查报出端口关闭与修复参考命令；Nokia 风格的配置图按配置上下文分组；翻译到华为', async ({ page, request }) => {
  const errors = collectErrors(page)
  const id = await nokiaDevice(request)

  // 检查：接入点所在端口缺省关闭
  await page.goto(`/check?device=${id}`)
  await expect(page.getByTestId('check-target')).toContainText('Nokia')
  const row = page.getByTestId('finding-row').filter({ hasText: 'port.shutdown_with_sap' }).first()
  await expect(row).toBeVisible()
  await row.click()
  await expect(page.getByTestId('finding-detail')).toBeVisible()
  await expect(page.getByTestId('detail-remedy')).toContainText('no shutdown')
  await expect(page.getByTestId('copy-remedy')).toBeVisible()
  await expectNoRawKeys(page)

  // 配置图：切到 Nokia 风格，interface[1/1/4] 显示为 port 1/1/4，自动按视图层级并插入 router Base / service 分组
  await page.goto(`/graph/${id}?node=${encodeURIComponent('interface[1/1/4]')}`)
  await style(page, 'nokia')
  await expect(page.getByTestId('node-detail').getByTestId('detail-name')).toHaveText('port 1/1/4')
  await expect(page.getByTestId('org-switch').locator('[data-org="tree"]')).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(async () => {
    const labels = await treeLabels(page)
    const groups = new Set(labels.map((l) => l.replace(/\s+\+?\d+$/, '')))
    return ['router Base', 'service', 'port'].map((g) => (groups.has(g) ? g : `缺少 ${g}；画出的节点：${labels.slice(0, 30).join(' | ')}`))
  }, { message: '树状图应有 router Base、service、port 分组' }).toEqual(['router Base', 'service', 'port'])
  await expectNoRawKeys(page)

  // 暗色主题截一次图
  await page.getByTestId('theme-switch').locator('button').nth(2).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.screenshot({ path: test.info().outputPath('m7-nokia-graph-dark.png') })

  // 翻译到华为 ATN
  await page.goto(`/translate?device=${id}&to=huawei-atn-v800r025`)
  await expect(page.getByTestId('tr-target')).toHaveValue('huawei-atn-v800r025')
  await page.getByTestId('tr-run').click()
  await expect(page.getByTestId('tr-verify')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('tr-out')).toContainText('interface')

  await style(page, 'huawei')
  expect(errors).toEqual([])
})
