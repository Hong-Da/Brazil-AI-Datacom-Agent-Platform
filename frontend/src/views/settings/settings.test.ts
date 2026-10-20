import { describe, expect, it } from 'vitest'
import { changedKeys, controlOf, pendingText, type SField, type SGroup } from './settings'

function f(key: string, kind: string, value: string | number | boolean, extra: Partial<SField> = {}): SField {
  return { key, kind, default: '', choices: [], min: null, max: null, secret: false, desc: key, value, source: 'file', restart: false, readonly: null, ...extra }
}

describe('系统设置（REQ-049）', () => {
  const groups: SGroup[] = [{ id: 'network', title: 'Net', fields: [f('server.host', 'host', '0.0.0.0'), f('server.port', 'port', 9090, { restart: true })] }]
  it('只算真正改了的项（"9090" 与 9090 相同）', () => {
    expect(changedKeys(groups, { 'server.port': '9090' })).toEqual([])
    expect(changedKeys(groups, { 'server.port': 9100, 'server.host': '0.0.0.0' })).toEqual(['server.port'])
  })
  it('控件：敏感值只显示是否已设置，选项与开关用下拉', () => {
    expect(controlOf(f('security.api_token', 'token', true, { secret: true }))).toBe('secret')
    expect(controlOf(f('log.level', 'choice', 'INFO'))).toBe('select')
    expect(controlOf(f('auth.registration', 'bool', 'false'))).toBe('select')
    expect(controlOf(f('history.keep', 'int', 50))).toBe('input')
  })
  it('待重启列表里敏感值显示是否已设置', () => {
    expect(pendingText(true, 'set', 'unset')).toBe('set')
    expect(pendingText(9100, 'set', 'unset')).toBe('9100')
  })
})
