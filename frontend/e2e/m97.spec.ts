import { expect, test, type Page } from '@playwright/test'
import { ADMIN, USER, collectErrors, login } from './helpers'

/** M9-7 评审修改：打开网页不闪主界面、语言图标按钮、偏好随账号保存（REQ-047）、向导与风格显示（REQ-048）、系统设置（REQ-049）。 */

test('没登录时打开网页：直接到登录页，主界面一次都没出现（REQ-048）', async ({ page }) => {
  await page.addInitScript(() => {
    const w = window as unknown as { __shellSeen: boolean }
    w.__shellSeen = false
    new MutationObserver(() => { if (document.querySelector('.shell, nav.nav')) w.__shellSeen = true })
      .observe(document, { childList: true, subtree: true })
  })
  await page.goto('/')
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByTestId('login-username')).toBeVisible()
  expect(await page.evaluate(() => (window as unknown as { __shellSeen: boolean }).__shellSeen)).toBe(false)
  await page.goto('/devices')
  await expect(page).toHaveURL(/\/login/)
  expect(await page.evaluate(() => (window as unknown as { __shellSeen: boolean }).__shellSeen)).toBe(false)
})

test('语言是图标按钮：点开选择语言，键盘可用；登录页也一样（REQ-047）', async ({ page }) => {
  await page.goto('/login')
  const btn = page.getByTestId('lang-switch')
  await expect(btn).toHaveAttribute('aria-haspopup', 'menu')
  await btn.click()
  await expect(page.getByTestId('lang-menu')).toBeVisible()
  await expect(page.getByTestId('lang-opt-pt-BR')).toContainText('Português (Brasil)')
  await page.getByTestId('lang-opt-en').click()
  await expect(page.getByTestId('lang-menu')).toBeHidden()
  await expect(btn).toContainText('EN')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  // 键盘：Esc 关闭
  await btn.click()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('lang-menu')).toBeHidden()
})

async function signIn(page: Page, who: { username: string; password: string }): Promise<void> {
  await page.goto('/login')
  await page.getByTestId('login-username').fill(who.username)
  await page.getByTestId('login-password').fill(who.password)
  await page.getByTestId('login').click()
  await expect(page).not.toHaveURL(/\/login/)
}

test('偏好随账号保存：换一个浏览器登录后沿用（REQ-047）', async ({ browser }) => {
  // 第一个浏览器：清掉账号里的偏好，登录后切换语言、主题、显示风格
  const a = await browser.newContext()
  const pa = await a.newPage()
  await login(pa, 'zh-CN', USER)
  await pa.goto('/')
  await expect(pa.getByTestId('nav-devices')).toBeVisible()
  await pa.getByTestId('lang-switch').click()
  await pa.getByTestId('lang-opt-pt-BR').click()
  await pa.getByTestId('theme-switch').getByRole('button').nth(2).click()
  await pa.getByTestId('style-switch').locator('[data-style="nokia"]').click()
  await expect.poll(async () => (await pa.request.get('/api/v1/me/prefs')).json().then((b) => b.data.prefs), { timeout: 5000 })
    .toMatchObject({ lang: 'pt-BR', theme: 'dark', term_style: 'nokia' })
  await pa.getByTestId('user-menu-button').click()
  await expect(pa.getByTestId('menu-prefs-sync')).toBeVisible()
  await a.close()

  // 第二个浏览器（本地是中文、浅色）：登录后用账号的值
  const b = await browser.newContext({ colorScheme: 'light' })
  const pb = await b.newPage()
  await signIn(pb, USER)
  await expect(pb.getByTestId('nav-devices')).toContainText('Dispositivos')
  await expect(pb.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(pb.getByTestId('style-switch').locator('[data-style="nokia"]')).toHaveAttribute('aria-pressed', 'true')
  await b.close()
})

test('切换显示风格后 Schema 视图与 Profile 管理直接显示对应叫法（REQ-048）', async ({ page }) => {
  await login(page)
  await page.goto('/profiles')
  await page.getByTestId('profile-row-huawei-atn-v800r023').click()
  const form = page.getByTestId('entry-row-vrf.instance').getByTestId('entry-form')
  await page.getByTestId('style-switch').locator('[data-style="huawei"]').click()
  await expect(form).toContainText('ip vpn-instance')
  await page.getByTestId('style-switch').locator('[data-style="cisco"]').click()
  await expect(form).toContainText('vrf definition') // 表格里直接换成 Cisco 的写法
  await page.goto('/schema')
  await expect(page.getByTestId('sv-style')).toContainText('Cisco')
  await page.getByTestId('style-switch').locator('[data-style="huawei"]').click()
  await expect(page.getByTestId('sv-style')).toContainText('华为')
})

test('系统设置：分组列出、标出需重启、保存后提示重启（REQ-049）', async ({ page }) => {
  const errors = collectErrors(page)
  await login(page)
  await page.goto('/')
  await page.getByTestId('nav-settings').click()
  await expect(page).toHaveURL(/\/settings$/)
  await expect(page.getByTestId('set-group-network')).toBeVisible()
  await expect(page.getByTestId('set-row-server.port').getByTestId('set-restart-tag')).toBeVisible()
  await expect(page.getByTestId('set-security.api_token')).toHaveCount(0) // 敏感值没有可编辑的输入框
  await expect(page.getByTestId('set-row-ui.term_style').locator('option[value="huawei"]')).toHaveText('华为')

  // 立即生效的项
  const keep = page.getByTestId('set-history.keep')
  const oldKeep = await keep.inputValue()
  await keep.fill('77')
  await expect(page.getByTestId('set-bar')).toBeVisible()
  await page.getByTestId('set-save').click()
  await expect(page.getByTestId('set-saved')).toBeVisible()

  // 不合格的值：逐项提示，不能保存
  const port = page.getByTestId('set-server.port')
  const oldPort = await port.inputValue()
  await port.fill('70000')
  await port.blur()
  await expect(page.getByTestId('set-row-server.port').locator('.err')).toBeVisible()
  await expect(page.getByTestId('set-save')).toBeDisabled()

  // 需要重启的项：保存后列出，页面不重启
  await port.fill('9399')
  await port.blur()
  await expect(page.getByTestId('set-save')).toBeEnabled()
  await page.getByTestId('set-save').click()
  await expect(page.getByTestId('set-restart')).toBeVisible()
  await expect(page.getByTestId('set-restart-server.port')).toContainText('9399')
  await page.reload()
  await expect(page.getByTestId('set-restart')).toBeVisible() // 重新打开仍提示

  // 还原
  await page.getByTestId('set-server.port').fill(oldPort)
  await page.getByTestId('set-history.keep').fill(oldKeep)
  await page.getByTestId('set-save').click()
  await expect(page.getByTestId('set-restart')).toBeHidden()
  expect(errors.filter((e) => !/422/.test(e))).toEqual([]) // 70000 的校验请求本来就返回 422
})

test('普通用户看不到系统设置', async ({ page }) => {
  await login(page, 'zh-CN', USER)
  await page.goto('/')
  await expect(page.getByTestId('nav-devices')).toBeVisible()
  await expect(page.getByTestId('nav-settings')).toHaveCount(0)
  await page.goto('/settings')
  await expect(page).not.toHaveURL(/\/settings/)
  void ADMIN
})

function wf(key: string, kind: string, def: string | number, extra: Record<string, unknown> = {}) {
  return { key, kind, default: def, choices: [], min: null, max: null, secret: false, desc: key, ...extra }
}
const SETUP = {
  groups: [
    { id: 'ui', title: '界面', fields: [wf('ui.language', 'choice', 'zh-CN', { choices: ['zh-CN', 'en', 'pt-BR'] }), wf('ui.term_style', 'choice', 'huawei', { choices: ['huawei', 'cisco', 'nokia'] })] },
    { id: 'network', title: '网络', fields: [wf('server.host', 'host', '0.0.0.0'), wf('server.port', 'port', 9090, { min: 1, max: 65535 })] },
    {
      id: 'ai', title: 'AI 接口', fields: [
        wf('ai.provider', 'choice', '', { choices: ['', 'anthropic', 'openai', 'local'] }), wf('ai.base_url', 'str', ''),
        wf('ai.api_key', 'secret', '', { secret: true }), wf('ai.model', 'str', ''),
      ],
    },
  ],
  addresses: ['0.0.0.0', '127.0.0.1'],
  languages: ['zh-CN', 'en', 'pt-BR'],
  config_path: 'E:/LucidMesh/config/config.toml',
  running: { 'server.host': '0.0.0.0', 'server.port': 9090 },
}

test('向导：紧凑布局（步骤栏、两列字段）、厂商名称首字母大写、AI 测试连接（REQ-048）', async ({ page }) => {
  const errors = collectErrors(page)
  let fail = false
  const sent: Record<string, unknown>[] = []
  await page.addInitScript(() => { localStorage.setItem('lmesh-lang', 'zh-CN') })
  await page.route('**/api/v1/health', (r) => r.fulfill({ json: { code: 0, message: 'OK', data: { configured: false } } }))
  await page.route('**/api/v1/setup', (r) => r.fulfill({ json: { code: 0, message: 'OK', data: r.request().method() === 'GET' ? SETUP : { valid: true } } }))
  await page.route('**/api/v1/setup/ai-test', async (r) => {
    sent.push(r.request().postDataJSON() as Record<string, unknown>)
    if (fail) return r.fulfill({ status: 502, json: { code: 1005, message: 'AI 接口调用失败', data: { error_type: 'AuthenticationError', status: 401 } } })
    return r.fulfill({ json: { code: 0, message: 'OK', data: { model: 'claude-x', reply: 'OK', tokens_in: 7, tokens_out: 1, elapsed_ms: 1234 } } })
  })
  await page.goto('/setup')
  await page.getByTestId('wizard-next').click() // 语言 → 界面

  // 显示风格不显示原始的 huawei / cisco / nokia
  const style = page.getByTestId('field-ui.term_style')
  await expect(style.locator('option')).toHaveText(['华为', 'Cisco', 'Nokia'])
  // 评审：空白太多 → 卡片居中、加宽，左侧步骤栏，高度随内容（1440 宽时不超过一屏的三分之二）
  const card = (await page.locator('.wz-card').boundingBox())!
  expect(card.width).toBeGreaterThan(1000)
  expect(Math.abs(card.x + card.width / 2 - 720)).toBeLessThan(3)
  expect(card.height).toBeLessThan(600)
  await expect(page.getByTestId('wizard-steps').locator('li')).toHaveCount(6)

  await page.getByTestId('wizard-next').click() // 界面
  await page.getByTestId('wizard-next').click() // 网络 → AI
  await page.getByTestId('wizard-ai-now').check()
  await page.getByTestId('field-ai.provider').selectOption('anthropic')
  await page.getByTestId('field-ai.api_key').fill('sk-e2e-secret')
  await page.getByTestId('field-ai.model').fill('claude-x')
  await expect(page.getByTestId('wizard-ai-test-result')).toContainText('还没有测试')
  // 两列：接口地址与 API Key 并排
  const u = (await page.getByTestId('field-ai.base_url').boundingBox())!
  const k = (await page.getByTestId('field-ai.api_key').boundingBox())!
  expect(Math.abs(u.y - k.y)).toBeLessThan(2)
  expect(k.x).toBeGreaterThan(u.x + u.width)
  await page.getByTestId('wizard-ai-test-btn').click()
  await expect(page.getByTestId('wizard-ai-test')).toHaveClass(/is-ok/)
  await expect(page.getByTestId('wizard-ai-test')).toContainText('claude-x')
  await expect(page.getByTestId('wizard-ai-test')).toContainText('1.2')
  expect(sent[0]).toMatchObject({ provider: 'anthropic', api_key: 'sk-e2e-secret', model: 'claude-x' })

  // 改了参数：旧结果作废；失败时说明原因
  fail = true
  await page.getByTestId('field-ai.model').fill('claude-y')
  await expect(page.getByTestId('wizard-ai-test')).toHaveClass(/is-idle/)
  await page.getByTestId('wizard-ai-test-btn').click()
  await expect(page.getByTestId('wizard-ai-test')).toHaveClass(/is-err/)
  await expect(page.getByTestId('wizard-ai-test-result')).toContainText('认证失败（401）')

  // 确认页里显示风格同样写成品牌名
  await page.getByTestId('wizard-next').click() // AI → 管理员
  await page.getByTestId('wizard-admin-password').fill('Admin-pass-1')
  await page.getByTestId('wizard-admin-password2').fill('Admin-pass-1')
  await page.getByTestId('wizard-next').click()
  await expect(page.getByTestId('wizard-cf-row-ui.term_style')).toContainText('华为')
  await expect(page.getByTestId('wizard-cf-row-ui.term_style')).not.toContainText('huawei')
  expect(errors.filter((e) => !/502/.test(e))).toEqual([])
})
