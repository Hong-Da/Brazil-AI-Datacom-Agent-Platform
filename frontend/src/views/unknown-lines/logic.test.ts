import { describe, expect, it } from 'vitest'
import { filterPatterns, patKey, patternParts, patternsToSend, stateOf, views, type UnknownPattern } from './logic'

const P: UnknownPattern[] = [
  { view: 'interface', pattern: 'mtu notanumber', count: 1, example: 'mtu notanumber' },
  { view: 'bgp', pattern: 'peer <ip> tracking delay <n>', count: 17, example: 'peer 10.0.0.1 tracking delay 5' },
  { view: 'interface', pattern: 'statistic enable', count: 5, example: 'statistic enable' },
]
const S = { 'statistic enable': 'pending', 'mtu notanumber': 'rejected' }

describe('未识别行', () => {
  it('状态：未送审为 new', () => {
    expect(stateOf(S, 'statistic enable')).toBe('pending')
    expect(stateOf(S, 'peer <ip> tracking delay <n>')).toBe('new')
    expect(stateOf({ x: 'weird' }, 'x')).toBe('new')
  })
  it('占位符拆分', () => {
    expect(patternParts('peer <ip> delay <n>')).toEqual([
      { text: 'peer ', ph: false }, { text: '<ip>', ph: true }, { text: ' delay ', ph: false }, { text: '<n>', ph: true },
    ])
    expect(patternParts('auto-frr')).toEqual([{ text: 'auto-frr', ph: false }])
  })
  it('筛选并按次数排序', () => {
    expect(filterPatterns(P, S, { q: '', view: '', state: '' }).map((p) => p.count)).toEqual([17, 5, 1])
    expect(filterPatterns(P, S, { q: '10.0.0.1', view: '', state: '' }).length).toBe(1)
    expect(filterPatterns(P, S, { q: '', view: 'interface', state: 'new' }).length).toBe(0)
    expect(filterPatterns(P, S, { q: '', view: '', state: 'rejected' })[0]!.pattern).toBe('mtu notanumber')
    expect(views(P)).toEqual(['bgp', 'interface'])
  })
  it('送审列表跳过已在审核中的', () => {
    const checked = new Set(P.map(patKey))
    expect(patternsToSend(P, checked, S).sort()).toEqual(['mtu notanumber', 'peer <ip> tracking delay <n>'])
  })
})
