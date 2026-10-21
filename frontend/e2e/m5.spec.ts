import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { collectErrors, login, TOKEN } from './helpers'

// M5：版本历史、表格导出、特性能力查询、AI 查询与护栏。e2e 服务未配置 AI：验证导航隐藏入口、降级页与“校验粘贴的配置”；
// AI 已配置时的问答流程用拦截请求返回的假回答（e2e/fixtures/m5-ask.json，来自假 AI 客户端的真实接口结果）。

const FIX = JSON.parse(readFileSync(fileURLToPath(new URL('./fixtures/m5-ask.json', import.meta.url)), 'utf-8'))

async function devices(request: APIRequestContext): Promise<{ id: number; name: string; versions: number }[]> {
  const r = await request.get('/api/v1/devices', { headers: { Authorization: `Bearer ${TOKEN}` } })
  return (await r.json()).data.devices
}
async function expectNoM5Keys(page: Page): Promise<void> {
  const text = await page.locator('main').innerText()
  const raw = text.match(/\b(history|export|features|ask)\.(?!json\b|cfg\b|keep\b)[a-zA-Z][\w.]*\b/g)
  expect(raw ?? [], `未翻译的文案键：${raw?.join(', ')}`).toEqual([])
}

test('导航：版本历史、表格导出、特性查询；未配置 AI 时不显示 AI 查询', async ({ page }) => {
  await login(page)
  await page.goto('/')
  for (const n of ['history', 'export', 'features']) await expect(page.getByTestId(`nav-${n}`)).toBeVisible()
  await expect(page.getByTestId('nav-ask')).toHaveCount(0)
  await page.getByTestId('nav-history').click()
  await expect(page).toHaveURL(/\/history/)
})

test('版本历史：ASR 920 两个快照 → 图差异、详情、配置差异、对象历史、回到 A、报告', async ({ page, request }) => {
  await login(page)
  const errors = collectErrors(page)
  const asr = (await devices(request)).find((d) => d.versions >= 2)!
  await page.goto(`/history/${asr.id}`)
  await expect(page.getByTestId('hist-timeline')).toBeVisible()
  await expect(page.getByTestId('hist-card-a')).toContainText('#1')
  await expect(page.getByTestId('hist-card-b')).toContainText('#2')
  await expect(page.getByTestId('hist-summary')).toBeVisible()
  const items = page.getByTestId('hist-item')
  await expect(items.first()).toBeVisible()
  await items.first().click()
  await expect(page.getByTestId('hist-detail')).toContainText('A')
  await page.getByTestId('hist-go-text').click()
  await expect(page.getByTestId('hist-text')).toBeVisible()
  await expect(page.locator('[data-testid="hist-text"] .tr.is-hl').first()).toBeVisible()
  await page.getByTestId('hist-tab-graph').click()
  // 切回图差异时仍选中刚才的对象
  await expect(items.first()).toHaveClass(/is-sel/)
  await page.getByTestId('hist-go-object').click()
  await expect(page.getByTestId('hist-obj-matrix')).toBeVisible()
  await expect(page.getByTestId('hist-obj-log')).toBeVisible()
  // 快照表与标签
  await page.getByTestId('hist-list-btn').click()
  await expect(page.getByTestId('hist-snap-table')).toBeVisible()
  // 回到 A 的变更脚本
  await page.getByTestId('hist-restore').click()
  await expect(page.getByTestId('hist-restore-dialog')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('hist-to-change')).toHaveAttribute('href', /\/change\?/)
  await page.locator('.modal-back').click({ position: { x: 5, y: 5 } })
  const dl = page.waitForEvent('download')
  await page.getByTestId('hist-report-en').click()
  expect((await dl).suggestedFilename()).toMatch(/\.en\.html$/)
  await expectNoM5Keys(page)
  expect(errors).toEqual([])
})

test('表格导出：IP 地址表预览 → 格子来源 → 换模板 → CSV 下载', async ({ page }) => {
  await login(page)
  const errors = collectErrors(page)
  await page.goto('/export')
  await expect(page.getByTestId('exp-table')).toBeVisible({ timeout: 30_000 })
  await page.getByTestId('exp-cell-0-0').click()
  await expect(page.getByTestId('exp-source')).toContainText('interface')
  await page.getByTestId('exp-preset-bgp-peer').click()
  await expect(page.getByTestId('exp-table')).toBeVisible()
  await expect(page.getByTestId('exp-table')).toContainText('derive:peer_remote_as')
  await page.getByTestId('exp-fmt-csv').check()
  const dl = page.waitForEvent('download')
  await page.getByTestId('exp-dl-en').click()
  expect((await dl).suggestedFilename()).toMatch(/\.csv$/)
  await expectNoM5Keys(page)
  expect(errors).toEqual([])
})

test('特性能力查询：搜 mtu → 由知识库计算的结论 → 格子详情 → Profile 对比与 CSV', async ({ page }) => {
  await login(page)
  const errors = collectErrors(page)
  await page.goto('/features')
  await page.getByTestId('feat-search').fill('mtu')
  await expect(page.getByTestId('feat-answer')).toContainText('interface.mtu')
  await page.locator('[data-testid^="feat-cell-interface.mtu-"]').first().click()
  await expect(page.getByTestId('feat-detail')).toContainText('interface.mtu')
  await page.getByTestId('feat-search').fill('zzz-no-such-feature')
  await expect(page.getByTestId('feat-empty')).toBeVisible()
  await page.getByTestId('feat-search').fill('')
  await page.getByTestId('feat-tab-compare').click()
  await expect(page.getByTestId('feat-cmp-strip')).toBeVisible()
  await expect(page.getByTestId('feat-cmp-table')).toBeVisible()
  const dl = page.waitForEvent('download')
  await page.getByTestId('feat-cmp-csv').click()
  expect((await dl).suggestedFilename()).toMatch(/\.csv$/)
  await expectNoM5Keys(page)
  expect(errors).toEqual([])
})

test('AI 查询（未配置 AI）：降级说明 + 校验粘贴的配置（拦截 / 通过 → 交给增量变更）', async ({ page }) => {
  await login(page)
  const errors = collectErrors(page)
  await page.goto('/ask')
  await expect(page.getByTestId('ask-off')).toBeVisible()
  await expect(page.getByTestId('nav-ask')).toBeVisible() // 当前页的入口保留
  await page.getByTestId('gen-device').selectOption('PE-ASR920-01')
  await page.getByTestId('guard-input').fill('interface Loopback98\n vrf forwarding NOPE-VRF\n')
  await page.getByTestId('guard-run').click()
  await expect(page.getByTestId('guard-verdict')).toHaveAttribute('data-verdict', 'blocked', { timeout: 30_000 })
  await expect(page.getByTestId('guard-issue').first()).toContainText('NOPE-VRF')
  await expect(page.locator('[data-testid="guard-lines"] .gl.bad')).toHaveCount(1)
  await page.getByTestId('guard-input').fill('interface Loopback99\n description E2E-TEST\n')
  await page.getByTestId('guard-run').click()
  await expect(page.getByTestId('guard-verdict')).toHaveAttribute('data-verdict', 'passed', { timeout: 30_000 })
  await page.getByTestId('guard-handoff').click()
  await expect(page).toHaveURL(/\/change\?/)
  await expect(page.getByTestId('chg-paste')).toHaveValue(/Loopback99/)
  await expectNoM5Keys(page)
  expect(errors).toEqual([])
})

test('AI 查询（REQ-051）：范围按网络、反选、隐藏或置灰只存原文的设备、顶部说明可折叠并随账号记住', async ({ page }) => {
  const errors = collectErrors(page)
  await login(page)
  await page.route('**/api/v1/ask/status', (r) => r.fulfill({ json: { code: 0, message: 'ok', data: FIX.status } }))
  // 范围里的设备按网络取：/projects/<项目>/n/<网络>/devices（一台能查询、一台只存原文）
  const devs = [
    { id: 901, name: 'R51-OK-01', vendor: 'cisco', profile: 'cisco-iosxe-asr920-17.15', versions: 1, latest_version_id: 1, sw_version: '', source_name: '', collected_at: null },
    { id: 902, name: 'R51-RAW-01', vendor: '', profile: '', versions: 1, latest_version_id: 2, sw_version: '', source_name: '', collected_at: null },
  ]
  await page.route(/\/api\/v1\/projects\/[^/]+\/n\/[^/]+\/devices$/, (r) => r.fulfill({ json: { code: 0, message: 'ok', data: { devices: devs } } }))
  await page.goto('/ask')
  await expect(page.getByTestId('ask-on')).toBeVisible()
  await expect(page.getByTestId('ask-scope-net')).toBeVisible()
  await expect(page.getByTestId('ask-scope-dev-901')).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('ask-scope-raw-902')).toBeDisabled()
  await expect(page.getByTestId('ask-scope-sum')).toContainText('1 / 1')
  // 清空后不能提问；全选后恢复
  await page.getByTestId('ask-input').fill('哪些接口没有描述？')
  await page.getByTestId('ask-scope-clear').click()
  await expect(page.getByTestId('ask-submit')).toBeDisabled()
  await page.getByTestId('ask-scope-invert').click()
  await expect(page.getByTestId('ask-scope-dev-901')).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('ask-submit')).toBeEnabled()
  // 隐藏只存原文的设备
  await page.getByTestId('ask-scope-hide-raw').check()
  await expect(page.getByTestId('ask-scope-raw-902')).toHaveCount(0)
  await page.getByTestId('ask-scope-hide-raw').uncheck()
  await expect(page.getByTestId('ask-scope-raw-902')).toBeDisabled()
  // 顶部说明收起后刷新仍收起（随账号保存），再展开
  await page.getByTestId('ask-intro-fold').click()
  await expect(page.getByTestId('ask-on')).toHaveClass(/is-folded/)
  await expect(page.locator('[data-testid="ask-on"] .rule')).toHaveCount(0)
  await page.waitForTimeout(800)
  await page.reload()
  await expect(page.getByTestId('ask-on')).toHaveClass(/is-folded/)
  await page.getByTestId('ask-intro-fold').click()
  await expect(page.locator('[data-testid="ask-on"] .rule')).toHaveCount(1)
  await page.waitForTimeout(800)
  expect(errors).toEqual([])
})

test('AI 查询会话（REQ-052～054）：保存、列表、重命名、附件、下载链接、AI 报告、归档', async ({ page }) => {
  const errors = collectErrors(page)
  await login(page)
  await page.route('**/api/v1/ask/status', (r) => r.fulfill({ json: { code: 0, message: 'ok', data: FIX.status } }))
  await page.route(/\/ask\/sessions\/\d+\/turns$/, (r) => r.fulfill({ json: { code: 0, message: 'ok', data: { id: 7001, position: 1, current: 0, versions: [{ question: FIX.ask.question, result: FIX.ask, context: 0, attachments: [], at: '2026-10-21T10:00:00Z' }] } } }))
  await page.route(/\/ask\/sessions\/\d+\/ai-report$/, (r) => r.fulfill({ json: { code: 0, message: 'ok', data: { markdown: '## 发现\n- R1\n', blocks: [{ type: 'h', level: 2, segments: [{ text: '发现', ok: true }] }, { type: 'li', level: 0, segments: [{ text: 'R1 上有 2 个接口。', ok: true }, { text: '还有 3 个没有描述。', ok: false }] }], verified: 1, unverified: 1, lang: 'zh-CN', filename: 'ask-session-1-ai-report.zh-CN.md' } } }))
  await page.goto('/ask')
  await expect(page.getByTestId('ask-rail')).toBeVisible()
  // 附件：先建会话再上传（文档提取文字，不需要 AI）
  await page.getByTestId('ask-attach-input').setInputFiles({ name: 'plan.csv', mimeType: 'text/csv', buffer: Buffer.from('接口,地址\nGE0/2/0,10.1.1.1/30\n') })
  await expect(page.getByTestId('ask-atts')).toContainText('plan.csv')
  await page.getByTestId('ask-input').fill(FIX.ask.question)
  await page.getByTestId('ask-submit').click()
  await expect(page.getByTestId('ask-answer')).toBeVisible()
  await expect(page.getByTestId('ask-csv-7001')).toHaveAttribute('href', /\/ask\/sessions\/\d+\/turns\/7001\/table\?format=csv/)
  await expect(page).toHaveURL(/[?&]s=\d+/)
  // 列表里有这个会话（提问被替换，后端没保存这一轮，标题在重命名后检查）；带 1 个附件
  await expect(page.getByTestId('ask-rail').locator('.it')).toHaveCount(1)
  await page.getByTestId('ask-ses-menu').click()
  await page.getByTestId('ask-ses-rename').click()
  await page.getByTestId('ask-ses-title-in').fill('VPN 会话')
  await page.getByTestId('ask-ses-title-ok').click()
  await expect(page.getByTestId('ask-ses-title')).toHaveText('VPN 会话')
  await expect(page.getByTestId('ask-rail')).toContainText('VPN 会话')
  // 下载菜单：会话报告链接、AI 报告（核对结果标出未经核对的句子）
  await page.getByTestId('ask-ses-dl').click()
  await expect(page.getByTestId('ask-dl-html-zh')).toHaveAttribute('href', /report\?lang=zh-CN&format=html/)
  const rep = await page.request.get((await page.getByTestId('ask-dl-md-en').getAttribute('href'))!)
  expect(rep.ok()).toBeTruthy()
  expect(await rep.text()).toContain('# AI Query Session Report')
  await page.getByTestId('ask-dl-ai').click()
  await expect(page.getByTestId('ask-ai-report')).toContainText('还有 3 个没有描述')
  await expect(page.getByTestId('ask-ai-report').locator('.unv')).toHaveCount(1)
  await page.getByTestId('ask-ai-report').getByRole('button', { name: /关闭/ }).last().click()
  // 归档后在“已归档”里，不能再提问
  await page.getByTestId('ask-ses-menu').click()
  await page.getByTestId('ask-ses-archive').click()
  await expect(page.getByTestId('ask-ses-restore')).toBeVisible()
  await expect(page.getByTestId('ask-input')).toHaveCount(0)
  await expect(page.getByTestId('ask-ses-tab-archived')).toHaveAttribute('aria-pressed', 'true')
  expect(errors).toEqual([])
})

test('AI 查询（假 AI）：三步过程、引用角标、逐句核对、更正文字、发送内容', async ({ page }) => {
  await login(page)
  await page.route('**/api/v1/ask/status', (r) => r.fulfill({ json: { code: 0, message: 'ok', data: FIX.status } }))
  // AI 查询属于项目接口（M6）：/api/v1/projects/<项目>/ask
  // REQ-052：提问保存在会话里（会话由后端真实创建），这里只替换会话里的提问：/ask/sessions/<编号>/turns
  await page.route(/\/ask\/sessions\/\d+\/turns$/, (r) => r.fulfill({ json: { code: 0, message: 'ok', data: { id: 7001, position: 1, current: 0, versions: [{ question: FIX.ask.question, result: FIX.ask, context: 0, attachments: [], at: '2026-10-21T10:00:00Z' }] } } }))
  await page.goto('/ask')
  await expect(page.getByTestId('ask-on')).toBeVisible()
  await page.getByTestId('ask-input').fill(FIX.ask.question)
  await page.getByTestId('ask-submit').click()
  await expect(page.getByTestId('ask-query')).toContainText('FIND')
  await expect(page.getByTestId('ask-result')).toBeVisible()
  const answer = page.getByTestId('ask-answer')
  await expect(answer.locator('[data-status="passed"]')).toHaveCount(2)
  await expect(answer.locator('[data-status="corrected"]')).toHaveCount(1)
  await expect(answer.locator('[data-status="unverifiable"]')).toHaveCount(1)
  await expect(page.getByTestId('ask-fixed')).toContainText('9999')
  await expect(page.getByTestId('ask-claims')).toBeVisible()
  await answer.locator('sup.cn').first().click()
  await expect(page.getByTestId('ask-evidence')).toContainText('GigabitEthernet0/2/0')
  await page.getByTestId('ask-sent').click()
  await expect(page.getByTestId('ask-sent-dialog')).toContainText('graph query language')
  await expectNoM5Keys(page)
})
