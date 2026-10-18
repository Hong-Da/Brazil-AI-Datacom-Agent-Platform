import { describe, expect, it } from 'vitest'
import { badVars, bodyCode, bodyLines, findClass, findingText, flattenRow, instanceRows, kindCounts, lineMarks, paramColumns, splitPlaceholders, varConstraint, varOf, varUses } from './logic'
import type { BlockInfo, Finding, VarInfo } from './types'

const body = 'hostname {{hostname}}\n{% repeat svc %}\ninterface BDI{{svc.vlan}}\n ip address {{svc.gw}} {{svc.lan|mask}}\n{% end %}\nend'
const vars: VarInfo[] = [
  { name: 'hostname', type: 'word', block: null, derived: false, example: 'PE-1' },
  { name: 'uplink_ip', type: 'word', block: null, derived: true, expr: 'uplink_net|host(2)' },
  { name: 'svc.vlan', type: 'vlan', block: 'svc', derived: false, unique: true },
  { name: 'svc.lan', type: 'prefix', block: 'svc', derived: false, within: ['10.0.0.0/8'], length: [24, 30] },
  { name: 'svc.gw', type: 'word', block: 'svc', derived: true, expr: 'svc.lan|host(1)' },
  { name: 'mgmt.vlan', type: 'vlan', block: 'mgmt', derived: false },
]
const blocks: BlockInfo[] = [{ name: 'svc', kind: 'repeat', min: 1, max: 4 }, { name: 'mgmt', kind: 'optional' }]
const f = (kind: Finding['kind'], extra: Partial<Finding> = {}): Finding => ({
  kind, severity: kind === 'extra' ? 'info' : 'error', block: null, instance: null, node: null, node_kind: null, schema: null, domain: null,
  actual_node: null, expected: null, actual: null, actual_origin: null, var: null, count: null, parent: null, lines: [], template_lines: [], ...extra,
})

describe('模板正文', () => {
  it('占位符与变量名', () => {
    expect(varOf('svc.lan|mask')).toBe('svc.lan')
    expect(splitPlaceholders('ip {{a}} {{b|mask}}!')).toEqual([{ s: 'ip ' }, { s: 'a', expr: 'a' }, { s: ' ' }, { s: 'b|mask', expr: 'b|mask' }, { s: '!' }])
  })
  it('块的范围、开始与结束', () => {
    const ls = bodyLines(body)
    expect(ls.map((l) => [l.no, l.block, l.mark, l.first, l.last])).toEqual([
      [1, null, null, false, false], [2, 'svc', 'start', false, false], [3, 'svc', null, true, false],
      [4, 'svc', null, false, true], [5, 'svc', 'end', false, false], [6, null, null, false, false],
    ])
    const code = bodyCode(body, 'svc.vlan')
    expect(code[2].cls).toContain('b-rep')
    expect(code[2].parts?.find((p) => p.v === 'svc.vlan')?.cls).toBe('vx is-hot')
    expect(varUses(body).get('svc.lan')).toBe(1)
  })
  it('约束摘要', () => {
    expect(varConstraint(vars[3])).toBe('within 10.0.0.0/8; len 24..30')
    expect(varConstraint(vars[1])).toBe('= uplink_net|host(2)')
    expect(varConstraint(vars[2])).toBe('unique')
  })
})

describe('校验发现', () => {
  it('分类、计数、行标记、违反约束的变量', () => {
    const fs = [f('missing'), f('value', { lines: [3] }), f('constraint', { var: 'svc.lan', lines: [3] }), f('extra', { lines: [3, 9] })]
    expect(fs.map(findClass)).toEqual(['missing', 'violation', 'violation', 'extra'])
    expect(kindCounts(fs)).toEqual({ missing: 1, violation: 2, extra: 1, info: 0 })
    const m = lineMarks(fs)
    expect(m.get(3)).toBe('c-viol')
    expect(m.get(9)).toBe('c-extra')
    expect([...badVars(fs)]).toEqual(['svc.lan'])
  })
  it('说明文字带参数与约束问题', () => {
    expect(findingText(f('value', { expected: '9216', actual: 9000 }), 'en')).toContain('9000')
    expect(findingText(f('constraint', { var: 'loopback', actual: '1.1.1.1', problem: 'template.value.not_within' }), 'zh-CN')).toContain('loopback')
  })
})

describe('参数表', () => {
  it('列：device、基础变量、可选块名、块变量（不含派生）', () => {
    expect(paramColumns(vars, blocks)).toEqual(['device', 'hostname', 'svc.vlan', 'svc.lan', 'mgmt', 'mgmt.vlan'])
  })
  it('提取的一行 → 参数表的一行', () => {
    const cols = paramColumns(vars, blocks)
    const row = { device: 'PE-1', hostname: 'PE-1', svc: [{ vlan: 101, lan: '10.0.1.0/24' }, { vlan: 102, lan: null }], mgmt: false }
    expect(flattenRow(row, cols, blocks)).toEqual({ device: 'PE-1', hostname: 'PE-1', 'svc.vlan': '101;102', 'svc.lan': '10.0.1.0/24;', mgmt: 'false', 'mgmt.vlan': '' })
  })
  it('块实例表', () => {
    const r = instanceRows({ svc: [{ vlan: 1, _node: 'x', _lines: [4, 5] }], mgmt: false })
    expect(r).toEqual([{ block: 'svc', i: 1, vals: [['vlan', 1]], lines: [4, 5] }])
  })
})
