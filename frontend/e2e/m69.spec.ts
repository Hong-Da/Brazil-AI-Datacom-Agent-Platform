import { expect, test, type Route } from '@playwright/test'
import { collectErrors, expectNoRawKeys, login } from './helpers'

/**
 * M6-9：M1 预览页评审修改。
 * 1. 向导确认页：按组汇总、突出改动、统一校验（有问题不能提交）、写入路径、需重启的项、返回修改后直接回到确认页。
 *    e2e 服务已完成首次配置，向导用到的 /health 与 /setup 在浏览器里替换成未配置实例的应答（字段结构与后端 wizard_schema 相同）。
 * 2. Schema 编辑：输入项随数据类型变化，换类型时提示不再适用的内容，可改回原类型。
 */

function field(key: string, kind: string, def: string | number, extra: Record<string, unknown> = {}) {
  return { key, kind, default: def, choices: [], min: null, max: null, secret: false, desc: key, ...extra }
}

const SETUP = {
  groups: [
    { id: 'ui', title: '界面', fields: [field('ui.language', 'choice', 'zh-CN', { choices: ['zh-CN', 'en', 'pt-BR'] })] },
    { id: 'network', title: '网络', fields: [field('server.host', 'host', '0.0.0.0'), field('server.port', 'port', 9090, { min: 1, max: 65535 })] },
    { id: 'security', title: '安全', fields: [field('security.api_token', 'token', '', { secret: true })] },
    { id: 'log', title: '日志', fields: [field('log.level', 'choice', 'info', { choices: ['debug', 'info', 'warning'] }), field('log.keep_days', 'int', 14)] },
    { id: 'ai', title: 'AI 接口', fields: [field('ai.provider', 'choice', '', { choices: ['', 'anthropic'] }), field('ai.api_key', 'secret', '', { secret: true })] },
  ],
  addresses: ['0.0.0.0', '127.0.0.1'],
  languages: ['zh-CN', 'en', 'pt-BR'],
  config_path: 'E:/LucidMesh/config/config.toml',
  running: { 'server.host': '0.0.0.0', 'server.port': 9090 },
}

test('向导确认页：汇总、统一校验、需重启的项与返回修改', async ({ page }) => {
  const errors = collectErrors(page)
  let busyPort = 0 // 模拟端口在填写之后被别的程序占用
  await page.addInitScript(() => { localStorage.setItem('lmesh-lang', 'zh-CN') })
  await page.route('**/api/v1/health', (r: Route) => r.fulfill({ json: { code: 0, message: 'OK', data: { configured: false } } }))
  await page.route('**/api/v1/setup', async (r: Route) => {
    if (r.request().method() === 'GET') return r.fulfill({ json: { code: 0, message: 'OK', data: SETUP } })
    const body = r.request().postDataJSON() as { values: Record<string, unknown>; dry_run?: boolean }
    if (busyPort && Number(body.values['server.port']) === busyPort) {
      return r.fulfill({ status: 422, json: { code: 1001, message: '参数错误', data: { errors: { 'server.port': '端口已被占用' } } } })
    }
    return r.fulfill({ json: { code: 0, message: 'OK', data: { valid: true } } })
  })

  await page.goto('/setup')
  await expect(page.getByTestId('wizard-lang')).toBeVisible()
  await page.getByTestId('wizard-next').click() // 语言
  await page.getByTestId('field-server.port').fill('9100')
  await page.getByTestId('wizard-next').click() // 网络
  await page.getByTestId('wizard-next').click() // 安全
  await page.getByTestId('wizard-next').click() // 日志
  await page.getByTestId('wizard-next').click() // AI（跳过）
  await page.getByTestId('wizard-admin-password').fill('Admin-pass-1')
  await page.getByTestId('wizard-admin-password2').fill('Admin-pass-1')
  await page.getByTestId('wizard-next').click() // 管理员

  // 确认页：检查通过、写入路径、改动与需重启的项、令牌只显示“完成时自动生成”
  await expect(page.getByTestId('wizard-cf-verdict')).toContainText('检查通过')
  await expect(page.getByTestId('wizard-cf-path')).toHaveText('E:/LucidMesh/config/config.toml')
  const port = page.getByTestId('wizard-cf-row-server.port')
  await expect(port).toHaveClass(/is-chg/)
  await expect(port).toContainText('默认：9090')
  await expect(port.getByTestId('wizard-cf-restart')).toBeVisible()
  await expect(page.getByTestId('wizard-cf-row-server.host')).toContainText('默认')
  await expect(page.getByTestId('wizard-cf-restart-note')).toContainText('端口')
  await expect(page.getByTestId('wizard-cf-row-security.api_token')).toContainText('完成时自动生成')
  await expect(page.getByTestId('wizard-sum-admin')).toContainText('已设置')
  await expect(page.getByTestId('wizard-sum-admin')).not.toContainText('Admin-pass-1')
  await expect(page.getByTestId('wizard-submit')).toBeEnabled()

  // 只看已修改：没改的分组收起
  await page.getByTestId('wizard-cf-only').click()
  await expect(page.getByTestId('wizard-sum-log')).toHaveCount(0)
  await expect(page.getByTestId('wizard-sum-network')).toBeVisible()

  // 端口被占用：重新检查后显示问题数，不能提交
  busyPort = 9100
  await page.getByTestId('wizard-cf-recheck').click()
  await expect(page.getByTestId('wizard-cf-verdict')).toContainText('有 1 个问题')
  await expect(port).toHaveClass(/is-err/)
  await expect(port).toContainText('端口已被占用')
  await expect(page.getByTestId('wizard-submit')).toBeDisabled()
  await expect(page.getByTestId('wizard-fix-first')).toBeVisible()

  // 返回修改：直接跳到网络一步，改完后一键回到确认页
  await page.getByTestId('wizard-cf-edit-network').click()
  await page.getByTestId('field-server.port').fill('9200')
  await page.getByTestId('wizard-to-confirm').click()
  await expect(page.getByTestId('wizard-cf-verdict')).toContainText('检查通过')
  await expect(page.getByTestId('wizard-cf-row-server.port')).toContainText('9200')
  await expect(page.getByTestId('wizard-submit')).toBeEnabled()

  // 窄屏可用：不出现横向滚动
  await page.setViewportSize({ width: 390, height: 800 })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
  expect(errors.filter((e) => !/422/.test(e))).toEqual([]) // 校验不通过时的 422 是预期的
})

test('Schema 编辑：输入项随数据类型变化，换类型时提示并可改回', async ({ page }) => {
  const errors = collectErrors(page)
  await login(page)
  await page.goto('/schema/edit?node=interface.mtu')
  const tp = page.getByTestId('se-tparams')
  await expect(tp).toHaveAttribute('data-type', 'integer')
  await expect(page.getByTestId('se-f-range-min')).toHaveValue('46')
  await expect(page.getByTestId('se-f-range-max')).toHaveValue('16000')
  await expect(page.getByTestId('se-f-choices')).toHaveCount(0)
  await expect(page.getByTestId('se-f-key')).toHaveCount(0)

  // 最小值大于最大值
  await page.getByTestId('se-f-range-min').fill('20000')
  await expect(page.getByTestId('se-err-range')).toBeVisible()
  await expect(page.getByTestId('se-save')).toBeDisabled()
  await page.getByTestId('se-f-range-min').fill('46')

  // 换成 enum：取值范围不再适用（提示），可选值必填
  await page.getByTestId('se-f-type').selectOption('enum')
  await expect(page.getByTestId('se-f-range-min')).toHaveCount(0)
  await expect(page.getByTestId('se-stale')).toContainText('取值范围')
  await expect(page.getByTestId('se-err-choices')).toBeVisible()
  await expect(page.getByTestId('se-save')).toBeDisabled()
  await page.getByTestId('se-f-choices').fill('jumbo')
  await page.getByTestId('se-f-choices').press('Enter')
  await page.getByTestId('se-f-choices').fill('standard')
  await page.getByTestId('se-f-choices').press('Enter')
  await expect(page.getByTestId('se-f-choice')).toHaveCount(2)
  await expect(page.getByTestId('se-err-choices')).toHaveCount(0)
  await expect(page.getByTestId('se-save')).toBeEnabled()

  // 格式类型只显示说明；object 显示键字段与有序；ref 只能选 object 节点
  await page.getByTestId('se-f-type').selectOption('ipv4')
  await expect(page.getByTestId('se-fmt')).toContainText('IPv4')
  await expect(page.getByTestId('se-stale')).toContainText('可选值')
  await page.getByTestId('se-f-type').selectOption('object')
  await expect(page.getByTestId('se-f-key')).toBeVisible()
  await expect(page.getByTestId('se-f-ordered')).toBeAttached()
  await page.getByTestId('se-f-type').selectOption('ref')
  await expect(page.getByTestId('se-err-ref')).toBeVisible()
  await expect(page.getByTestId('se-f-ref').locator('option[value="interface"]')).toHaveCount(1)
  await expect(page.getByTestId('se-f-ref').locator('option[value="interface.mtu"]')).toHaveCount(0)
  await page.getByTestId('se-f-type').selectOption('boolean')
  await expect(page.getByTestId('se-tp-none')).toBeVisible()

  // 改回原类型：取值范围还在；刚才填的可选值对 integer 不适用，仍会提示
  await page.getByTestId('se-stale-undo').click()
  await expect(tp).toHaveAttribute('data-type', 'integer')
  await expect(page.getByTestId('se-stale')).toContainText('可选值')
  await expect(page.getByTestId('se-stale')).not.toContainText('取值范围')
  await expect(page.getByTestId('se-stale-undo')).toHaveCount(0)
  await expect(page.getByTestId('se-f-range-max')).toHaveValue('16000')
  await expectNoRawKeys(page)
  expect(errors).toEqual([])
})
