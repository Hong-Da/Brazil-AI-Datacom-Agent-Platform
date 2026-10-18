import { describe, expect, it } from 'vitest'
import { blocksOf, coerce, displayHost, displayValue, initialValues, isChanged, labelKey, pickErrors, visibleGroups, type WField, type WGroup } from './wizard'

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
