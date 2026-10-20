import { describe, expect, it } from 'vitest'
import { blocksOf, coerce, confirmRows, confirmStats, groupErrors, needsRestart, displayHost, displayValue, initialValues, isChanged, labelKey, pickErrors, visibleGroups, type WField, type WGroup } from './wizard'

function f(key: string, kind: string, def: string | number = '', extra: Partial<WField> = {}): WField {
  return { key, kind, default: def, choices: [], min: null, max: null, secret: false, desc: key, ...extra }
}

const GROUPS: WGroup[] = [
  { id: 'ui', title: 'UI', fields: [f('ui.language', 'choice', 'zh-CN')] },
  { id: 'network', title: 'Net', fields: [f('server.host', 'host', '0.0.0.0'), f('server.port', 'port', 9000)] },
  { id: 'data', title: 'Data', fields: [f('database.url', 'dburl', '', { secret: true }), f('knowledge.dir', 'path', 'data/knowledge')] },
  { id: 'ai', title: 'AI', fields: [f('ai.provider', 'choice', '', { choices: ['', 'anthropic'] }), f('ai.base_url', 'str'), f('ai.api_key', 'secret', '', { secret: true })] },
]

describe('向导逻辑', () => {
  it('界面语言单独一步，只含语言的分组不显示', () => {
    expect(visibleGroups(GROUPS).map((g) => g.id)).toEqual(['network', 'data', 'ai'])
  })

  it('监听地址与端口并成一块，数据库与 AI 用专门的排布', () => {
    const [net, data, ai] = visibleGroups(GROUPS)
    expect(blocksOf(net).map((b) => b.type)).toEqual(['hostport'])
    const hp = blocksOf(net)[0]
    expect(hp.type === 'hostport' && hp.port?.key).toBe('server.port')
    expect(blocksOf(data).map((b) => b.type)).toEqual(['dburl', 'field'])
    expect(blocksOf(data)[1]).toMatchObject({ needsAi: false })
    expect(blocksOf(ai).map((b) => b.type)).toEqual(['ai', 'field', 'field'])
    expect(blocksOf(ai)[1]).toMatchObject({ needsAi: true })
  })

  it('没有端口时监听地址单独一块', () => {
    const b = blocksOf({ id: 'n', title: '', fields: [f('server.host', 'host')] })
    expect(b).toEqual([{ type: 'hostport', host: expect.objectContaining({ key: 'server.host' }), port: null }])
  })

  it('初始值取默认值，已填写的保留', () => {
    expect(initialValues(GROUPS, { 'server.port': 9100 })).toMatchObject({ 'server.host': '0.0.0.0', 'server.port': 9100, 'ai.provider': '' })
  })

  it('是否改过默认值按文字比较', () => {
    const port = f('server.port', 'port', 9000)
    expect(isChanged(port, '9000')).toBe(false)
    expect(isChanged(port, 9001)).toBe(true)
    expect(isChanged(f('a.b', 'str'), undefined)).toBe(false)
  })

  it('汇总显示：空值为 null，敏感值遮住，数据库地址只遮密码', () => {
    expect(displayValue(f('a.b', 'str'), '')).toBeNull()
    expect(displayValue(f('ai.api_key', 'secret', '', { secret: true }), 'sk-1')).toBe('••••••')
    expect(displayValue(f('database.url', 'dburl', '', { secret: true }), 'postgresql+psycopg://u:p%40ss@h:5432/db')).toBe('postgresql+psycopg://u:••••••@h:5432/db')
    expect(displayValue(f('server.port', 'port'), 9000)).toBe('9000')
  })

  it('只取本组字段的错误', () => {
    expect(pickErrors({ 'server.port': 'busy', 'ai.base_url': 'req' }, ['server.host', 'server.port'])).toEqual({ 'server.port': 'busy' })
  })

  it('整数输入转成数字，非法输入原样交给后端', () => {
    expect(coerce(f('server.port', 'port'), '9100')).toBe(9100)
    expect(coerce(f('server.port', 'port'), 'abc')).toBe('abc')
    expect(coerce(f('ai.model', 'str'), '42')).toBe('42')
  })

  it('文案键与示例地址', () => {
    expect(labelKey('server.host')).toBe('wizard.lbl.server_host')
    expect(displayHost('0.0.0.0')).toBe('127.0.0.1')
    expect(displayHost('10.0.0.5')).toBe('10.0.0.5')
  })
})

describe('确认页（M6-9）', () => {
  const groups = visibleGroups([
    ...GROUPS,
    { id: 'security', title: 'Sec', fields: [f('security.api_token', 'token', '', { secret: true })] },
  ])
  const running = { 'server.host': '0.0.0.0', 'server.port': 9000 }

  it('改过的项、敏感值只给已设置 / 未设置、与运行中不同的监听地址需要重启', () => {
    const values = { ...initialValues(groups, {}), 'server.port': 9100, 'security.api_token': 'secret-token' }
    const net = confirmRows(groups[0]!, values, {}, running)
    expect(net.map((r) => [r.field.key, r.changed, r.restart])).toEqual([['server.host', false, false], ['server.port', true, true]])
    const sec = confirmRows(groups[3]!, values, {}, running)
    expect(sec[0]).toMatchObject({ secretState: 'set', changed: true })
    expect(confirmRows(groups[3]!, { ...values, 'security.api_token': '' }, {}, running)[0]!.secretState).toBe('unset')
    // 数据库地址不是“已设置 / 未设置”，而是遮住密码后显示
    expect(confirmRows(groups[1]!, values, {}, running)[0]!.secretState).toBeNull()
    expect(needsRestart('server.port', 9000, running)).toBe(false)
    expect(needsRestart('log.level', 'debug', running)).toBe(false)
  })

  it('只看已修改时保留出错的项；AI 未配置时只显示“未配置”', () => {
    const values = initialValues(groups, {})
    expect(confirmRows(groups[0]!, values, { 'server.host': 'bad' }, running, true).map((r) => r.field.key)).toEqual(['server.host'])
    expect(confirmRows(groups[2]!, values, {}, running)).toEqual([])
    expect(confirmRows(groups[2]!, { ...values, 'ai.provider': 'anthropic' }, {}, running).length).toBe(3)
  })

  it('汇总：改动数、默认数、需重启项与问题数（含管理员）', () => {
    const values = { ...initialValues(groups, {}), 'server.port': 9100 }
    const errs = { 'server.port': 'busy', 'admin.password': 'short', 'other.key': 'x' }
    const st = confirmStats(groups, values, errs, running)
    expect(st).toEqual({ changed: 1, unchanged: 4, restart: ['server.port'], errors: 2 })
    expect(groupErrors(groups[0]!, errs)).toBe(1)
  })
})

describe('M9-7 选项文字与 AI 测试结果（REQ-048）', () => {
  it('显示风格、AI 接口类型、开关用文案键，不显示原始值', async () => {
    const { optionKey } = await import('./wizard')
    expect(optionKey('ui.term_style', 'choice', 'huawei')).toBe('style.huawei')
    expect(optionKey('ui.term_style', 'choice', 'nokia')).toBe('style.nokia')
    expect(optionKey('ai.provider', 'choice', 'openai')).toBe('wizard.prov_openai')
    expect(optionKey('ai.provider', 'choice', '')).toBe('wizard.none')
    expect(optionKey('auth.registration', 'bool', 'true')).toBe('wizard.on')
    expect(optionKey('log.level', 'choice', 'INFO')).toBeNull()
  })
  it('测试失败的原因按 HTTP 状态码与异常类型归类', async () => {
    const { aiTestReason } = await import('./wizard')
    expect(aiTestReason(401, 'AuthenticationError')).toBe('wizard.aiTestAuth')
    expect(aiTestReason(null, 'PermissionDeniedError')).toBe('wizard.aiTestAuth')
    expect(aiTestReason(404, 'NotFoundError')).toBe('wizard.aiTestNotFound')
    expect(aiTestReason(null, 'APITimeoutError')).toBe('wizard.aiTestTimeout')
    expect(aiTestReason(null, 'APIConnectionError')).toBe('wizard.aiTestConnect')
    expect(aiTestReason(500, 'InternalServerError')).toBe('wizard.aiTestOther')
  })
})
