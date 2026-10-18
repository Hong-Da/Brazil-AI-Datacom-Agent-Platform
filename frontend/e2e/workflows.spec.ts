import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { collectErrors, expectNoRawKeys, login } from './helpers'

/**
 * 各页面的真实流程（文件名排在 shell.spec.ts 之后：本文件会发布知识库版本，改变共享后端的状态）。所有用例共享 e2e_server.py 建的同一个后端，按本文件顺序执行：
 * 前面的用例修改的数据（导入的设备、送审的未识别行、知识库修改）会被后面的用例用到，
 * 依赖关系在每个用例的注释里写明。
 */

const ATN = 'ORG-364464' // 华为 ATN 样本（设备名已脱敏）
const LAB = 'LAB-ATN-09' // 含 1 行未识别行
const NEW_CFG = [
  'version 17.15',
  'hostname E2E-CS-01',
  '!',
  'interface GigabitEthernet0/0/1',
  ' description e2e uplink',
  ' mtu 9000',
  '!',
  'end',
  '',
].join('\n')
const TEST_NODE = 'interface.e2e_probe'

test.beforeEach(async ({ page }) => {
  await login(page)
})

/** 设备配置图的 cytoscape 实例挂在容器的 _cyreg 上：取一个节点的屏幕坐标，用真实鼠标点击。 */
async function graphNodePoint(page: Page, selector: string): Promise<{ x: number; y: number; id: string }> {
  const canvas = page.getByTestId('graph-canvas')
  const box = (await canvas.boundingBox())!
  const handle = await canvas.evaluateHandle((el) => (el as unknown as { _cyreg: { cy: unknown } })._cyreg.cy)
  await expect.poll(() => handle.evaluate((cy: any) => cy.nodes().length), { timeout: 15_000 }).toBeGreaterThan(1)
  // 等布局动画结束
  let last = ''
  await expect.poll(async () => {
    const now = await handle.evaluate((cy: any) => JSON.stringify(cy.nodes().map((n: any) => n.renderedPosition())))
    const same = now === last
    last = now
    return same
  }, { intervals: [300, 300, 300, 500, 500, 1000] }).toBe(true)
  const p = await handle.evaluate((cy: any, sel: string) => {
    const w = cy.width(), h = cy.height()
    // 图比视野高时目标可能在视野外：先把第一个匹配的节点移到视野中央（与用户平移画布一样）
    const first = cy.nodes(sel)[0]
    if (first) cy.center(first)
    const n = cy.nodes(sel).filter((x: any) => {
      const r = x.renderedPosition()
      return r.x > 10 && r.y > 10 && r.x < w - 10 && r.y < h - 10
    })[0]
    if (!n) return { dbg: `w=${w} h=${h} zoom=${cy.zoom()} total=${cy.nodes().length} match=${cy.nodes(sel).length} ` + cy.nodes().slice(0, 12).map((x: any) => `${x.id()}[${x.classes().join('.')}]@${Math.round(x.renderedPosition().x)},${Math.round(x.renderedPosition().y)}`).join(' ') }
    const r = n.renderedPosition()
    return { x: r.x, y: r.y, id: n.id() as string }
  }, selector)
  expect((p as any).dbg, `图上没有可见的节点匹配 ${selector}`).toBeUndefined()
  return { x: box.x + p!.x, y: box.y + p!.y, id: p!.id }
}

test('首页：概况数字与设备数一致，运行全部往返测试后样本全部一致', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('/')
  const strip = page.getByTestId('summary-strip')
  await expect(strip).toBeVisible()
  await expect(page.getByTestId('recent-imports')).toContainText('3')
  await expect(page.getByTestId('recent-imports').locator('a.imp')).toHaveCount(3)
  // 未识别行：1 种模式
  await expect(strip).toContainText('1')
  await expect(page.getByTestId('rt-never')).toBeVisible()

  await page.getByTestId('run-roundtrips').click()
  const table = page.getByTestId('rt-table')
  await expect(table).toBeVisible({ timeout: 120_000 })
  const rows = table.locator('tbody tr.rt-row')
  expect(await rows.count()).toBeGreaterThan(0)
  await expect(table.locator('tbody tr.rt-row.fail')).toHaveCount(0)
  const n = await rows.count()
  await expect(strip).toContainText(`${n} / ${n}`)
  // 只看失败：没有失败项
  await page.getByTestId('rt-filter').selectOption('fail')
  await expect(table.locator('tbody tr.rt-row')).toHaveCount(0)
  await expectNoRawKeys(page)
  expect(errors).toEqual([])
})

test('设备与导入：3 台设备，上传一份新配置后变成 4 台，按状态筛选有未识别行', async ({ page }) => {
  await page.goto('/devices')
  const table = page.getByTestId('devices-table')
  await expect(table.getByTestId('device-link')).toHaveCount(3)
  await expect(table).toContainText(ATN)
  await expect(table).toContainText('PE-ASR920-01')

  await page.getByTestId('open-import').click()
  const dlg = page.getByTestId('import-dialog')
  await expect(dlg).toBeVisible()
  await dlg.getByTestId('file-input').setInputFiles({ name: 'e2e-cs-01.cfg', mimeType: 'text/plain', buffer: Buffer.from(NEW_CFG) })
  await expect(dlg.getByTestId('chosen-files')).toContainText('e2e-cs-01.cfg')
  await dlg.getByTestId('to-level').click()
  await expect(dlg.getByTestId('sanitize-level')).toBeVisible()
  await dlg.getByTestId('start-import').click()
  const res = dlg.getByTestId('import-results')
  await expect(res).toContainText('e2e-cs-01.cfg', { timeout: 60_000 })
  await expect(res).toContainText('E2E-CS-01')
  await expect(res.locator('tr.failed')).toHaveCount(0)
  await dlg.getByTestId('import-done').click()
  await expect(dlg).toBeHidden()

  await expect(table.getByTestId('device-link')).toHaveCount(4)
  await expect(table).toContainText('E2E-CS-01')

  await page.getByTestId('filter-state').selectOption('unknown')
  await expect(table.getByTestId('device-link')).toHaveCount(1)
  await expect(table.getByTestId('device-link')).toHaveText(LAB)
  await page.getByTestId('filter-state').selectOption('')
  await page.getByTestId('device-search').fill('PE-ASR')
  await expect(table.getByTestId('device-link')).toHaveCount(1)
  await expect(table.getByTestId('device-link')).toHaveText('PE-ASR920-01')
})

test('设备配置图：选中节点后详情与原文高亮联动，往返测试一致', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('/devices')
  await page.getByTestId('devices-table').getByTestId('device-link').filter({ hasText: ATN }).click()
  await expect(page).toHaveURL(/\/graph\/\d+/)
  await expect(page.locator('main h1')).toHaveText(ATN)
  await expect(page.getByTestId('graph-canvas')).toBeVisible()
  const detail = page.getByTestId('node-detail')
  const text = page.getByTestId('config-text')
  await expect(text.locator('[data-ln]').first()).toBeVisible()
  await expect(text.locator('.is-hl')).toHaveCount(0)

  // 图 → 详情 + 原文：点一个接口节点
  // 大图默认收起到功能域：先点 interface 功能域展开下一层，再点一个接口对象
  const dom = await graphNodePoint(page, '[id = "domain:interface"]')
  await page.mouse.click(dom.x, dom.y)
  await expect(detail.locator('.d-name')).toHaveText('interface')
  const pt = await graphNodePoint(page, '.k-object')
  await page.mouse.click(pt.x, pt.y)
  await expect(detail.locator('.d-name')).not.toHaveText('interface')
  await expect(detail.locator('.d-name')).toBeVisible()
  const name = (await detail.locator('.d-name').innerText()).trim()
  expect(name.length).toBeGreaterThan(0)
  await expect(text.locator('.is-hl').first()).toBeVisible()

  // 原文 → 详情：点一行 interface 配置，详情切到该接口，该行高亮
  const line = text.locator('[data-ln]').filter({ hasText: /^\s*\d+\s*interface \S+/ }).first()
  const lineText = (await line.locator('.t').innerText()).trim()
  await line.click()
  await expect(line).toHaveClass(/is-hl/)
  await expect(detail.locator('.d-name')).toContainText(lineText.replace(/^interface\s+/, ''))
  await expect(detail.getByTestId('line-chips')).toBeVisible()

  await page.getByTestId('btn-roundtrip').click()
  const rt = page.getByTestId('roundtrip-result')
  await expect(rt).toBeVisible({ timeout: 60_000 })
  await expect(rt).toHaveClass(/ok/)
  expect(errors).toEqual([])
})

test('设备配置图：未识别行可逐个跳转并标出', async ({ page }) => {
  await page.goto('/devices')
  await page.getByTestId('devices-table').getByTestId('device-link').filter({ hasText: LAB }).click()
  const text = page.getByTestId('config-text')
  await expect(text.locator('.unknown')).toHaveCount(1)
  await expect(text.locator('.unknown')).toContainText('mtu notanumber')
  await page.getByTestId('next-unknown').click()
  await expect(page.getByTestId('node-detail')).toContainText('mtu notanumber')
  await expect(page.getByTestId('node-detail').getByTestId('goto-unknown')).toBeVisible()
})

test('未识别行：能看到 mtu 一行，送审后状态变为已送审，审核队列出现 unknown_line', async ({ page }) => {
  await page.goto('/unknown-lines')
  const table = page.getByTestId('unknown-table')
  const row = page.getByTestId('unknown-row').filter({ hasText: 'mtu notanumber' })
  await expect(row).toHaveCount(1)
  await expect(row).toContainText('interface')
  const summary = page.getByTestId('unknown-summary')
  await expect(summary).toContainText('1 / 4')

  await row.locator('input[type=checkbox]').check()
  await page.getByTestId('batch-send').click()
  await expect(page.locator('.toast')).toBeVisible()
  await expect(row.locator('.tag')).toHaveClass(/pending/)
  await expect(page.getByTestId('unknown-detail').getByTestId('send-one')).toHaveCount(0)
  await page.getByTestId('filter-state').selectOption('pending')
  await expect(table.getByTestId('unknown-row')).toHaveCount(1)
  await page.getByTestId('filter-state').selectOption('new')
  await expect(table.getByTestId('unknown-row')).toHaveCount(0)

  await page.getByTestId('filter-state').selectOption('')
  await page.getByTestId('unknown-detail').getByRole('link', { name: /审核/ }).first().click()
  await expect(page).toHaveURL(/\/review\?kind=unknown_line/)
  const list = page.getByTestId('review-list')
  await expect(list.locator('.it')).toHaveCount(1)
  await expect(page.getByTestId('review-detail')).toContainText('mtu notanumber')
})

test('审核队列：按类型筛选，通过一张命令卡后计数减少', async ({ page }) => {
  await page.goto('/review')
  const counts = page.getByTestId('review-counts')
  await expect(counts).toBeVisible()
  const kind = page.getByTestId('review-kind')
  // 依赖上一个用例：队列里有命令卡和 1 条未识别行
  await expect(kind.locator('option[value=unknown_line]')).toHaveCount(1)
  await kind.selectOption('unknown_line')
  await expect(page).toHaveURL(/kind=unknown_line/)
  await expect(page.getByTestId('review-list').locator('.it')).toHaveCount(1)

  await kind.selectOption('card')
  await expect(page).toHaveURL(/kind=card/)
  const cardOpt = kind.locator('option[value=card]')
  const before = Number((await cardOpt.innerText()).match(/（(\d+)）/)![1])
  expect(before).toBeGreaterThan(0)
  const first = page.getByTestId('review-list').locator('.it').first()
  await expect(first).toHaveClass(/is-sel/)
  const detail = page.getByTestId('review-detail')
  await expect(detail.getByTestId('review-approve')).toBeEnabled()
  await detail.getByTestId('review-approve').click()
  await expect(page.getByTestId('review-toast')).toBeVisible()
  await expect(cardOpt).toHaveText(new RegExp(`（${before - 1}）`))
  await expect(counts).toContainText(String(before - 1))
})

test('Schema 视图：切换 Profile 与对比模式', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('/schema')
  await expect(page.getByTestId('sv-graph')).toBeVisible()
  const nodes = page.getByTestId('sv-node')
  expect(await nodes.count()).toBeGreaterThan(50)

  const mode = page.getByTestId('sv-mode')
  await mode.getByRole('button').nth(0).click()
  await page.getByTestId('sv-profile-a').selectOption('cisco-iosxe-asr920-17.15')
  await expect(page.getByTestId('sv-inactive')).toBeVisible()
  const inactiveCisco = await page.getByTestId('sv-inactive').locator('.ditem').count()
  await page.getByTestId('sv-profile-a').selectOption('huawei-atn-v800r025')
  await expect.poll(() => page.getByTestId('sv-inactive').locator('.ditem').count()).not.toBe(inactiveCisco)

  // 点一个节点：侧栏显示它在各 Profile 的支持情况
  await page.locator('[data-testid=sv-node][data-id="interface.mtu"]').click()
  await expect(page.getByTestId('sv-per-profile')).toBeVisible()
  await expect(page.getByTestId('sv-side')).toContainText('interface.mtu')

  await page.getByTestId('sv-clear-sel').click()
  await mode.getByRole('button').nth(1).click()
  await expect(mode.getByRole('button').nth(1)).toHaveAttribute('aria-pressed', 'true')
  await page.getByTestId('sv-profile-a').selectOption('huawei-atn-v800r025')
  await page.getByTestId('sv-profile-b').selectOption('cisco-iosxe-asr920-17.15')
  // 华为与 Cisco 有差异：仅一方支持的节点或默认值不同
  await expect.poll(async () => {
    let n = 0
    for (const k of ['onlyA', 'onlyB', 'defaults']) n += await page.getByTestId(`sv-cmp-${k}`).locator('.ditem').count()
    return n
  }).toBeGreaterThan(0)
  await page.getByTestId('sv-only-diff').check()
  const shown = await nodes.count()
  expect(shown).toBeGreaterThan(0)
  await expectNoRawKeys(page)
  expect(errors).toEqual([])
})

test('Schema 管理：新建、修改、删除测试节点；被使用的节点删除时显示阻塞原因', async ({ page }) => {
  test.setTimeout(120_000) // 每次写入都会提交知识库仓库，较慢
  // 知识库从未发布过时 /kb/draft 的 changes 为 null，页面不能因此报错
  const errors = collectErrors(page)
  await page.goto('/schema/edit')
  const tree = page.getByTestId('se-tree')
  await expect(tree.getByTestId('se-tree-item').first()).toBeVisible()

  // 被使用的节点：删除被阻塞
  await page.getByTestId('se-filter').fill('interface.mtu')
  await tree.locator('[title="interface.mtu"]').click()
  await expect(page.getByTestId('se-f-type')).toBeVisible()
  await page.getByTestId('se-delete').click()
  const modal = page.getByTestId('se-modal')
  await expect(modal.getByTestId('se-del-blocked')).toBeVisible()
  await expect(modal.locator('.reflist')).toContainText(/huawei-atn|cisco-iosxe/)
  await expect(modal.getByTestId('se-del-confirm')).toHaveCount(0)
  await modal.getByRole('button', { name: '取消' }).click()
  await expect(modal).toBeHidden()

  // 新建子节点
  await page.getByTestId('se-filter').fill('')
  await tree.locator('[title="interface"]').click()
  await page.getByTestId('se-new-child').click()
  await expect(page.getByTestId('se-f-id')).toHaveValue('interface.')
  await page.getByTestId('se-f-id').fill(TEST_NODE)
  await page.getByTestId('se-f-sem-zh-CN').fill('端到端测试节点')
  await page.getByTestId('se-f-sem-en').fill('E2E probe node')
  await page.getByTestId('se-f-type').selectOption('string')
  await page.getByTestId('se-save').click()
  await expect(page.getByTestId('se-toast')).toContainText(TEST_NODE)
  await expect(tree.locator(`[title="${TEST_NODE}"]`)).toBeVisible()
  // e2e 知识库从未发布过：草稿区说明“首次发布”，而不是“没有修改”
  await expect(page.getByTestId('se-draft').getByTestId('se-draft-first')).toBeVisible()
  await expect(page.getByTestId('se-draft')).toContainText(/次提交|commit/)

  // 修改
  await page.getByTestId('se-f-sem-en').fill('E2E probe node, edited')
  await expect(page.getByTestId('se-save')).toBeEnabled()
  await page.getByTestId('se-save').click()
  await expect(page.getByTestId('se-toast')).toContainText(`已保存到草稿区：${TEST_NODE}`)
  await expect(page.getByTestId('se-save')).toBeDisabled()
  await page.reload()
  await expect(page.getByTestId('se-f-sem-en')).toHaveValue('E2E probe node, edited')

  // 删除：没有被使用，可以删
  await page.getByTestId('se-delete').click()
  await expect(modal.getByTestId('se-del-free')).toBeVisible()
  await modal.getByTestId('se-del-confirm').click()
  await expect(modal).toBeHidden()
  await expect(page.getByTestId('se-toast')).toContainText(TEST_NODE)
  await expect(tree.locator(`[title="${TEST_NODE}"]`)).toHaveCount(0)
  expect(errors).toEqual([])
})

test('Profile 管理：覆盖继承条目的默认值，对比页显示差异；新建 Profile', async ({ page }) => {
  await page.goto('/profiles')
  await page.getByTestId('profile-row-huawei-atn-v800r023').click()
  await expect(page.getByTestId('profile-fresh')).toBeVisible()
  await page.getByTestId('entries-q').fill('interface.mtu')
  await page.getByTestId('entry-row-interface.mtu').click()
  const editor = page.getByTestId('entry-editor')
  await expect(editor.getByTestId('entry-default')).toHaveValue('1500')
  await editor.getByTestId('entry-override').click()
  await editor.getByTestId('entry-default').fill('9000')
  await editor.getByTestId('entry-save').click()
  await expect(page.getByTestId('profiles-toast')).toBeVisible()
  await expect(editor.getByTestId('entry-restore')).toBeVisible()
  await expect(editor.getByTestId('entry-default')).toHaveValue('9000')
  await expect(page.getByTestId('profile-fresh')).toHaveCount(0)

  await page.getByTestId('tab-compare').click()
  await page.getByTestId('compare-a').selectOption('huawei-atn-v800r023')
  await page.getByTestId('compare-b').selectOption('huawei-atn-v800r025')
  const cmp = page.getByTestId('compare-table')
  const row = cmp.locator('tbody tr').filter({ hasText: 'interface.mtu' })
  await expect(row).toHaveCount(1)
  await expect(row).toContainText('9000')
  await expect(row).toContainText('1500')
  await expect(row).toHaveClass(/d-default/)

  // 新建 Profile（继承 v800r025）
  await page.getByTestId('profiles-new').click()
  const dlg = page.getByTestId('new-profile-dialog')
  await dlg.getByTestId('new-id').fill('huawei-atn-e2e')
  await dlg.getByTestId('new-title').fill('E2E Profile')
  await dlg.getByTestId('new-inherits').selectOption('huawei-atn-v800r025')
  await dlg.getByTestId('new-version').fill('^V800R099')
  await dlg.getByTestId('new-submit').click()
  await expect(dlg).toBeHidden()
  await expect(page.getByTestId('profiles-toast')).toContainText('huawei-atn-e2e')
  await expect(page.getByTestId('profile-row-huawei-atn-e2e')).toBeVisible()
  await expect(page.getByTestId('profile-row-huawei-atn-e2e')).toHaveClass(/is-sel/)
})

test('覆盖矩阵：只看缺口筛选生效，导出 CSV', async ({ page }) => {
  await page.goto('/coverage')
  const table = page.getByTestId('coverage-table')
  await expect(table).toBeVisible()
  const nodeRows = table.locator('tbody tr:not(.grp)')
  const all = await nodeRows.count()
  expect(all).toBeGreaterThan(50)
  await page.locator('label.check').filter({ has: page.getByTestId('coverage-gaps') }).click()
  await expect(page.getByTestId('coverage-gaps')).toBeChecked()
  await expect.poll(() => nodeRows.count()).toBeLessThan(all)
  const gaps = await nodeRows.count()
  expect(gaps).toBeGreaterThan(0)
  await expect(table.locator('tbody tr:not(.grp):not(.gap)')).toHaveCount(0)

  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByTestId('coverage-export').click()])
  expect(dl.suggestedFilename()).toMatch(/^coverage_.*\.csv$/)
  const csv = readFileSync((await dl.path())!, 'utf8')
  // 表头 + 每个缺口节点一行
  expect(csv.trim().split(/\r?\n/).length).toBe(gaps + 1)
})

test('知识库版本：草稿区显示前面的修改，发布一个版本', async ({ page }) => {
  test.setTimeout(240_000) // 发布会跑校验与样本回归
  await page.goto('/releases')
  // 依赖前面的用例：Profile 默认值覆盖、新建 Profile
  await expect(page.getByTestId('release-list')).toBeVisible()
  const draft = page.getByTestId('draft-changes')
  await expect(draft).toBeVisible()
  const firstRelease = await draft.locator('table').count() === 0
  if (!firstRelease) await expect(page.getByTestId('draft-table')).toContainText('interface.mtu')

  await page.getByTestId('publish-version').fill('0.1.0')
  await page.getByTestId('publish-message').fill('e2e release')
  await page.getByTestId('publish-btn').click()
  await expect(page.getByTestId('publish-ok')).toBeVisible({ timeout: 180_000 })
  await expect(page.getByTestId('publish-ok')).toContainText('0.1.0')
  await expect(page.getByTestId('release-list')).toContainText('0.1.0')
  await expect(page.getByTestId('kb-chip')).toContainText('0.1.0')
  await page.getByTestId('tab-log').click()
  await expect(page.getByTestId('changelog')).toContainText('e2e release')
})

test('文档与知识库包：导出知识库包，再用它做导入预览', async ({ page }, info) => {
  await page.goto('/ingest?tab=pkg')
  await expect(page.getByTestId('pkg-export')).toBeVisible()
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByTestId('pkg-export-btn').click()])
  expect(dl.suggestedFilename()).toMatch(/^lmesh-kb-.*\.zip$/)
  const zip = info.outputPath('kb.zip')
  await dl.saveAs(zip)

  await page.getByTestId('pkg-file').setInputFiles(zip)
  const valid = page.getByTestId('pkg-check-valid')
  await expect(valid).toBeVisible({ timeout: 60_000 })
  await expect(valid).toHaveClass(/ok/)
  await expect(page.getByTestId('pkg-error')).toHaveCount(0)
  // 与当前知识库完全相同：没有新增与冲突，没有可导入的内容
  await expect(page.getByTestId('pkg-conflicts')).toHaveCount(0)
  await expect(page.getByTestId('pkg-import-btn')).toBeDisabled()
})

test('AI 接口：未配置时显示降级说明；保存本地模型接口后刷新仍在，再改回未配置', async ({ page }) => {
  await page.goto('/ai')
  await expect(page.getByTestId('ai-degraded')).toBeVisible()
  const provider = page.getByTestId('ai-provider')
  await provider.locator('label').filter({ hasText: /本地/ }).locator('input').check()
  await page.getByTestId('ai-base-url').fill('http://127.0.0.1:11434/v1')
  await page.getByTestId('ai-api-key').fill('e2e-secret-key')
  await page.getByTestId('ai-model').fill('qwen2.5:7b')
  await expect(page.getByTestId('ai-dirty')).toBeVisible()
  await page.getByTestId('ai-save').click()
  await expect(page.getByTestId('ai-dirty')).toHaveCount(0)
  await expect(page.getByTestId('ai-degraded')).toHaveCount(0)

  await page.reload()
  await expect(page.getByTestId('ai-base-url')).toHaveValue('http://127.0.0.1:11434/v1')
  await expect(page.getByTestId('ai-model')).toHaveValue('qwen2.5:7b')
  await expect(page.getByTestId('ai-key-set')).toBeVisible()
  await expect(page.getByTestId('ai-api-key')).toHaveValue('')
  await expect(page.getByTestId('ai-test')).toBeEnabled()

  await provider.locator('label').last().locator('input').check()
  await page.getByTestId('ai-save').click()
  await expect(page.getByTestId('ai-degraded')).toBeVisible()
  await page.reload()
  await expect(page.getByTestId('ai-degraded')).toBeVisible()
  await expect(page.getByTestId('ai-base-url')).toHaveCount(0)
})

// 回归：发布后草稿统计要对比已发布版本，快照按提交缓存并在发布后后台预加载，首页不应再等几秒
test('发布版本后首页概况仍能在 3 秒内加载', async ({ page }) => {
  // 依赖前面“知识库版本”用例已发布 0.1.0
  const t0 = Date.now()
  await page.goto('/')
  await expect(page.getByTestId('summary-strip')).toBeVisible()
  await expect(page.getByTestId('kb-chip')).toContainText('0.1.0')
  expect(Date.now() - t0).toBeLessThan(3_000)
})
