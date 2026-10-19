import { describe, expect, it } from 'vitest'
import { descendantCount, domainKeep, foldAll, hiddenByFold, indexScript, revealLine, rowIndex, segments, visibleRows, windowOf } from './script'
import type { ScriptData } from './types'

/** 与后端 tests/unit/test_layers.py 的小样本同构（行号、区间由后端 core/config_analysis.py 计算）。 */
const S: ScriptData = {
  device: 'R1',
  profile: 'huawei-atn-v800r025',
  family: 'huawei-vrp8',
  lines: [
    { no: 1, kind: 'raw', text: 'sysname R1', depth: 0, parent: null, node: 'raw[1]', layer: null, domain: '' },
    { no: 2, kind: 'separator', text: '#', depth: 0, parent: null },
    { no: 3, kind: 'command', text: 'ip vpn-instance RAN', depth: 0, parent: null, node: 'vrf.instance[RAN]', layer: 'network', domain: 'vrf', spans: [{ s: 0, e: 2, t: 'kw' }, { s: 3, e: 15, t: 'kw' }, { s: 16, e: 19, t: 'param', p: 'vpn-instance-name' }] },
    { no: 4, kind: 'command', text: ' ipv4-family', depth: 1, parent: 3, node: 'vrf.instance[RAN]/af[ipv4]', layer: 'network', domain: 'vrf', spans: [{ s: 1, e: 12, t: 'kw' }] },
    { no: 5, kind: 'command', text: '  route-distinguisher 65000:1', depth: 2, parent: 4, node: 'vrf.instance[RAN]/af[ipv4]/rd', layer: 'network', domain: 'vrf' },
    { no: 6, kind: 'separator', text: '#', depth: 0, parent: null },
    { no: 7, kind: 'command', text: 'interface GigabitEthernet0/2/1', depth: 0, parent: null, node: 'interface[GigabitEthernet0/2/1]', layer: 'physical', domain: 'interface' },
    {
      no: 8, kind: 'command', text: ' ip binding vpn-instance RAN', depth: 1, parent: 7, node: 'interface[GigabitEthernet0/2/1]/vrf', layer: 'network', domain: 'vrf',
      spans: [{ s: 1, e: 3, t: 'kw' }, { s: 4, e: 11, t: 'kw' }, { s: 12, e: 24, t: 'kw' }, { s: 25, e: 28, t: 'ref', p: 'vpn-instance-name', ref: ['vrf.instance[RAN]'] }],
    },
    { no: 9, kind: 'unknown', text: ' foo bar', depth: 1, parent: 7, node: 'unknown[9]', layer: 'physical', domain: 'interface' },
    { no: 10, kind: 'end', text: 'return', depth: 0, parent: null },
  ],
  refs: { 'vrf.instance[RAN]': [8] },
  defs: { 'vrf.instance[RAN]': 3 },
  defaults: [
    { node: 'interface[GigabitEthernet0/2/1]/mtu', owner: 'interface[GigabitEthernet0/2/1]', schema: 'interface.mtu', value: 1500, after: 9, depth: 1, text: 'mtu 1500' },
    { node: 'vrf.instance[RAN]/af[ipv4]/label_mode', owner: 'vrf.instance[RAN]/af[ipv4]', schema: 'vrf.instance.af.label_mode', value: 'per-instance', after: 5, depth: 2, text: null },
  ],
}

describe('结构化脚本', () => {
  const ix = indexScript(S)

  it('索引：子行、引用、默认值插入位置', () => {
    expect(ix.kids.get(3)).toEqual([4])
    expect(ix.kids.get(7)).toEqual([8, 9])
    expect(ix.refs.get('vrf.instance[RAN]')).toEqual([8])
    expect(ix.defaultsAfter.get(9)?.[0].node).toBe('interface[GigabitEthernet0/2/1]/mtu')
    expect(ix.defaultByNode.has('vrf.instance[RAN]/af[ipv4]/label_mode')).toBe(true)
  })

  it('折叠：被折叠的上级挡住的行不显示，折叠行后显示后代数', () => {
    const fold = new Set([3])
    expect(hiddenByFold(ix, 5, fold)).toBe(true)
    expect(hiddenByFold(ix, 3, fold)).toBe(false)
    const rows = visibleRows(S, ix, { fold, domain: '', showDefaults: false })
    expect(rows.map((r) => (r.type === 'line' ? r.no : r.d.node))).toEqual([1, 2, 3, 6, 7, 8, 9, 10])
    expect(descendantCount(ix, 3)).toBe(2)
    expect([...foldAll(ix)].sort()).toEqual([3, 7])
    expect([...revealLine(ix, 5, new Set([3, 4, 7]))]).toEqual([7])
  })

  it('默认值行插在所属块末尾；块折叠时不显示', () => {
    const rows = visibleRows(S, ix, { fold: new Set(), domain: '', showDefaults: true })
    const order = rows.map((r) => (r.type === 'line' ? String(r.no) : `d:${r.d.schema}`))
    expect(order).toEqual(['1', '2', '3', '4', '5', 'd:vrf.instance.af.label_mode', '6', '7', '8', '9', 'd:interface.mtu', '10'])
    const folded = visibleRows(S, ix, { fold: new Set([7]), domain: '', showDefaults: true })
    expect(folded.some((r) => r.type === 'def' && r.d.schema === 'interface.mtu')).toBe(false)
    expect(rowIndex(rows, { node: 'interface[GigabitEthernet0/2/1]/mtu' })).toBe(10)
    expect(rowIndex(rows, { line: 8 })).toBe(8)
  })

  it('按功能域筛选：保留该功能域的行与它的上级', () => {
    expect([...(domainKeep(S, ix, 'vrf') ?? [])].sort((a, b) => a - b)).toEqual([3, 4, 5, 7, 8])
    const rows = visibleRows(S, ix, { fold: new Set(), domain: 'interface', showDefaults: false })
    expect(rows.map((r) => (r.type === 'line' ? r.no : 0))).toEqual([7, 9])
    expect(domainKeep(S, ix, '')).toBeNull()
  })

  it('按字符区间切成着色片段：引用带目标，空白原样保留', () => {
    const seg = segments(S.lines[7])
    expect(seg.map((s) => s.text).join('')).toBe(' ip binding vpn-instance RAN')
    expect(seg.filter((s) => s.cls).map((s) => [s.text, s.cls])).toEqual([['ip', 'kw'], ['binding', 'kw'], ['vpn-instance', 'kw'], ['RAN', 'rf']])
    expect(seg.find((s) => s.cls === 'rf')?.ref).toBe('vrf.instance[RAN]')
    expect(segments(S.lines[0])).toEqual([{ text: 'sysname R1', cls: '' }])
    // 越界或重叠的区间忽略
    expect(segments({ ...S.lines[2], spans: [{ s: 0, e: 99, t: 'kw' }] })).toEqual([{ text: 'ip vpn-instance RAN', cls: '' }])
  })

  it('虚拟滚动窗口', () => {
    expect(windowOf(0, 400, 20, 2300)).toEqual([0, 40])
    expect(windowOf(20000, 400, 20, 2300)).toEqual([980, 1040])
    expect(windowOf(45900, 400, 20, 2300)).toEqual([2275, 2300])
    expect(windowOf(0, 400, 20, 5)).toEqual([0, 5])
  })
})
