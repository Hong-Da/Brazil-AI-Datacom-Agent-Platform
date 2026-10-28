import { describe, expect, it } from 'vitest'
import {
  buildRows, countTypes, describe as describeNode, domainsOf, explain, filterRows, fmtValue, groupRows, lineClass,
  prettySeg, sideOf, splitPath, stepRow,
} from './logic'
import { buildTree, extrasFromGraph, initialCollapsed, layoutTree, prefixMap, toCanonical } from './tree'
import { initialRows, mainInterfaces, mapCsvRows, mergePairs, parseMapCsv, setRow, toInterfaceMap } from './ifmap'
import { compareBody, dispositionName, fromQuery, ready, reportName, swapSides, toQuery, defaultOptions, emptySide, type Setup } from './setup'
import type { CompareResult, Diff } from './types'

const diff = (o: Partial<Diff>): Diff => ({
  kind: 'changed', node_kind: 'attr', node: 'x', schema: null, domain: 'interface', a: null, b: null,
  from: null, to: null, similarity: null, count: null, related: [], ...o,
})

// 取自演示后端 PE-ASR920-01 两个版本的真实对比结果（节选）
const result: CompareResult = {
  a: { label: 'PE-ASR920-01@12', device: 'PE-ASR920-01', profile: 'cisco-iosxe-asr920-17.15', family: 'cisco-iosxe', kb_version: '0.1.0', device_id: 12, version_id: 12, nodes: 162 },
  b: { label: 'PE-ASR920-01@17', device: 'PE-ASR920-01', profile: 'cisco-iosxe-asr920-17.15', family: 'cisco-iosxe', kb_version: '0.1.0', device_id: 12, version_id: 17, nodes: 154 },
  options: {},
  equal: false,
  diffs: [
    diff({ node: 'interface[GigabitEthernet0/0/0]/mtu', schema: 'interface.mtu', a: { node: 'interface[GigabitEthernet0/0/0]/mtu', value: 9216, origin: 'explicit', lines: [39] }, b: { node: 'interface[GigabitEthernet0/0/0]/mtu', value: 9000, origin: 'explicit', lines: [39] } }),
    diff({ kind: 'removed', node_kind: 'object', domain: 'vrf', node: 'vrf.instance[RAN-2G]/af[ipv4]/rt[value=64512:1,direction=import]', a: { node: 'vrf.instance[RAN-2G]/af[ipv4]/rt[value=64512:1,direction=import]', value: { value: '64512:1', direction: 'import' }, origin: 'explicit', lines: [29] }, count: 2 }),
    diff({ kind: 'removed', node_kind: 'object', domain: 'bgp', node: 'bgp.instance[64512]/bgp.peer[10.255.0.2]', a: { node: 'bgp.instance[64512]/bgp.peer[10.255.0.2]', value: '10.255.0.2', origin: 'explicit', lines: [89] }, count: 3 }),
    diff({
      kind: 'renamed', node_kind: 'object', domain: 'routing-policy', node: 'rp.policy[EXPORT-LO]', schema: 'rp.policy',
      a: { node: 'rp.policy[EXPORT-LOOPBACK]', value: 'EXPORT-LOOPBACK', origin: 'explicit', lines: [117, 118] },
      b: { node: 'rp.policy[EXPORT-LO]', value: 'EXPORT-LO', origin: 'explicit', lines: [114, 115] },
      from: 'EXPORT-LOOPBACK', to: 'EXPORT-LO', similarity: 1, related: ['bgp.instance[64512]/bgp.af[afi=ipv4,vrf=]/peer[RR]/export_policy'],
    }),
    diff({
      kind: 'changed', domain: 'routing-policy', node: 'rp.policy[EXPORT-LO]/node[10]/action',
      a: { node: 'rp.policy[EXPORT-LOOPBACK]/node[10]/action', value: 'permit', origin: 'default', lines: [] },
      b: { node: 'rp.policy[EXPORT-LO]/node[10]/action', value: 'deny', origin: 'explicit', lines: [116] },
    }),
  ],
  renames: [],
  unknown: { a: [], b: [{ line: 7, text: 'foo bar', owner: '' }] },
  default_only: [{ node: 'interface[GigabitEthernet0/0/0]/negotiation', schema: 'interface.negotiation', domain: 'interface', side: 'b', value: 'auto' }],
  summary: { total: 5, by_kind: { added: 0, removed: 2, changed: 2, renamed: 1 }, by_domain: {}, unknown: { a: 0, b: 1 }, default_only: 1 },
}

describe('编号与显示', () => {
  it('按 / 拆分，方括号里的 / 不拆', () => {
    expect(splitPath('interface[GigabitEthernet0/0/0]/mtu')).toEqual(['interface[GigabitEthernet0/0/0]', 'mtu'])
    expect(splitPath('raw[a > b/c]')).toEqual(['raw[a > b/c]'])
    expect(splitPath('')).toEqual([])
  })
  it('段的显示与主副行', () => {
    expect(prettySeg('peer[10.0.0.1]')).toBe('peer 10.0.0.1')
    expect(prettySeg('mtu')).toBe('mtu')
    expect(describeNode('interface[Gi0/0/0]/mtu', 'attr')).toEqual({ o: 'interface Gi0/0/0', a: 'mtu' })
    expect(describeNode('bgp.instance[1]/bgp.peer[2.2.2.2]', 'object')).toEqual({ o: 'bgp.peer 2.2.2.2', a: 'bgp.instance 1' })
  })
  it('有效值文字', () => {
    expect(fmtValue({ value: '1:1', direction: 'import' })).toBe('value=1:1 · direction=import')
    expect(fmtValue(['a', 'b'])).toBe('a, b')
    expect(fmtValue(null)).toBe('')
    expect(fmtValue(false)).toBe('false')
  })
})

describe('差异行', () => {
  const rows = buildRows(result)
  it('changed 显示为 modified，default_only 为不可比，改名对象下的差异是子行', () => {
    expect(rows.map((r) => r.type)).toEqual(['modified', 'removed', 'removed', 'renamed', 'modified', 'na'])
    expect(rows[4].child).toBe(true)
    expect(rows[3].child).toBe(false)
  })
  it('两侧的值与来源', () => {
    expect(sideOf(rows[0], 'a')).toEqual({ text: '9216', origin: 'explicit', lines: [39] })
    expect(sideOf(rows[1], 'b').origin).toBe('absent')
    expect(sideOf(rows[5], 'b')).toEqual({ text: 'auto', origin: 'default', lines: [] })
    expect(sideOf(rows[5], 'a').origin).toBe('absent')
  })
  it('筛选：类型、功能域、搜索，不可比项默认折叠', () => {
    const f = { type: '' as const, domain: '', q: '', showNa: false }
    expect(filterRows(rows, f)).toHaveLength(5)
    expect(filterRows(rows, { ...f, showNa: true })).toHaveLength(6)
    expect(filterRows(rows, { ...f, type: 'na' })).toHaveLength(1)
    expect(filterRows(rows, { ...f, type: 'removed' })).toHaveLength(2)
    expect(filterRows(rows, { ...f, domain: 'bgp' })).toHaveLength(1)
    expect(filterRows(rows, { ...f, q: 'export-loopback' }).map((r) => r.id)).toEqual(['d3', 'd4'])
    expect(filterRows(rows, { ...f, q: '9000' })).toHaveLength(1)
  })
  it('计数与分组保持后端顺序，并给出每组折叠的不可比项数', () => {
    expect(countTypes(rows)).toEqual({ added: 0, removed: 2, modified: 2, renamed: 1, na: 1 })
    const vis = filterRows(rows, { type: '', domain: '', q: '', showNa: false })
    const g = groupRows(vis, rows, false)
    expect(g.map((x) => x.domain)).toEqual(['interface', 'vrf', 'bgp', 'routing-policy'])
    expect(g[0].folded).toBe(1)
    expect(g[3].counts.renamed).toBe(1)
    expect(domainsOf(rows)).toEqual(['interface', 'vrf', 'bgp', 'routing-policy'])
  })
  it('判定依据由字段推出', () => {
    expect(explain(rows[0])).toEqual({ key: 'why.changed', params: { a: '9216', b: '9000' } })
    expect(explain(rows[1])).toEqual({ key: 'why.removedObj', params: { n: 2 } })
    expect(explain(rows[3])).toEqual({ key: 'why.renamed', params: { from: 'EXPORT-LOOPBACK', to: 'EXPORT-LO', sim: 100, n: 1 } })
    expect(explain(rows[4]).key).toBe('why.changedDefault')
    expect(explain(rows[5])).toEqual({ key: 'why.na', params: { side: 'B', other: 'A', v: 'auto' } })
    expect(explain({ ...rows[0], diff: diff({ node_kind: 'raw', kind: 'added' }) }).key).toBe('why.raw')
  })
  it('原文行样式与键盘移动', () => {
    expect(lineClass('removed', 'a')).toBe('d-del')
    expect(lineClass('added', 'b')).toBe('d-add')
    expect(lineClass('modified', 'a')).toBe('d-mod')
    expect(stepRow(rows, 'd1', 1)).toBe('d2')
    expect(stepRow(rows, 'd0', -1)).toBe('d0')
    expect(stepRow(rows, null, 1)).toBe('d0')
    expect(stepRow([], null, 1)).toBeNull()
  })
})

describe('差异图', () => {
  const rows = buildRows(result)
  const tree = buildTree(rows, 'A ⇢ B')
  it('设备 → 功能域 → 对象 → 属性，上级汇总为修改', () => {
    expect(tree.root.children.map((c) => c.key)).toEqual(['D:interface', 'D:vrf', 'D:bgp', 'D:routing-policy'])
    const mtu = tree.byKey.get('interface|interface[GigabitEthernet0/0/0]/mtu')!
    expect(mtu.state).toBe('mod')
    expect(mtu.label).toBe('mtu 9216 ⇢ 9000')
    expect(mtu.labelA).toBe('mtu 9216')
    expect(mtu.parent!.state).toBe('mod')
    expect(tree.byKey.get('D:bgp')!.state).toBe('mod')
    const ren = tree.byKey.get('routing-policy|rp.policy[EXPORT-LO]')!
    expect(ren.state).toBe('ren')
    expect(ren.label).toBe('rp.policy EXPORT-LOOPBACK ⇢ EXPORT-LO')
    expect(tree.byRow.get('d3')).toBe(ren.key)
  })
  it('引用方不在差异里时补成“随改名”节点并画引用边', () => {
    const k = 'bgp|bgp.instance[64512]/bgp.af[afi=ipv4,vrf=]/peer[RR]/export_policy' // 放在已有上级 bgp.instance[64512] 所在的功能域下
    expect(tree.byKey.get(k)!.state).toBe('ref')
    expect(tree.refs).toEqual([{ from: k, to: 'routing-policy|rp.policy[EXPORT-LO]', state: 'ren' }])
  })
  it('A 侧隐藏新增、B 侧隐藏删除；收起的节点显示隐藏数', () => {
    const all = layoutTree(tree, { side: 'both', collapsed: new Set() })
    const onlyB = layoutTree(tree, { side: 'b', collapsed: new Set() })
    expect(onlyB.nodes.some((n) => n.state === 'del')).toBe(false)
    expect(all.nodes.some((n) => n.state === 'del')).toBe(true)
    expect(all.refs).toHaveLength(1)
    const col = layoutTree(tree, { side: 'both', collapsed: new Set(['D:routing-policy']) })
    const dom = col.nodes.find((n) => n.key === 'D:routing-policy')!
    expect(dom.collapsed).toBe(true)
    expect(dom.hidden).toBe(3)
    expect(col.refs).toHaveLength(1) // 被引用端收进功能域时弧线连到功能域节点
    const both = layoutTree(tree, { side: 'both', collapsed: new Set(['dev']) })
    expect(both.refs).toHaveLength(0) // 两端都收进同一个节点时不画
    // 同一深度同一列，父节点在子节点中间
    const xs = new Set(all.nodes.filter((n) => n.depth === 1).map((n) => n.x))
    expect(xs.size).toBe(1)
    expect(all.width).toBeGreaterThan(0)
    expect(all.height).toBeGreaterThan(0)
  })
  it('节点多时默认收起到功能域', () => {
    expect(initialCollapsed(tree).size).toBe(0)
    expect([...initialCollapsed(tree, 5)]).toEqual(['D:interface', 'D:vrf', 'D:bgp', 'D:routing-policy'])
  })
  it('显示全部：图里的原始编号换成规范编号后补成无变化节点', () => {
    const m = prefixMap(rows)
    expect(m.get('rp.policy[EXPORT-LOOPBACK]')).toBe('rp.policy[EXPORT-LO]')
    expect(toCanonical('rp.policy[EXPORT-LOOPBACK]/node[20]', m)).toBe('rp.policy[EXPORT-LO]/node[20]')
    expect(toCanonical('interface[Gi0/0/1]', m)).toBe('interface[Gi0/0/1]')
    const sd = new Map([['interface', 'interface'], ['interface.mtu', 'interface'], ['rp.policy.node', 'routing-policy']])
    const extras = extrasFromGraph([
      { id: 'device', kind: 'device', schema: null },
      { id: 'interface[Gi0/0/1]', kind: 'object', schema: 'interface' },
      { id: 'interface[GigabitEthernet0/0/0]/mtu', kind: 'attr', schema: 'interface.mtu' },
      { id: 'rp.policy[EXPORT-LOOPBACK]/node[20]', kind: 'object', schema: 'rp.policy.node' },
    ], sd, m)
    expect(extras).toEqual([
      { node: 'interface[Gi0/0/1]', domain: 'interface' },
      { node: 'interface[GigabitEthernet0/0/0]/mtu', domain: 'interface' },
      { node: 'rp.policy[EXPORT-LO]/node[20]', domain: 'routing-policy' },
    ])
    const t2 = buildTree(rows, 'A ⇢ B', extras)
    expect(t2.byKey.get('interface|interface[Gi0/0/1]')!.state).toBe('same')
    expect(t2.byKey.get('interface|interface[GigabitEthernet0/0/0]/mtu')!.state).toBe('mod') // 已有差异节点不被覆盖
    expect(t2.byKey.get('routing-policy|rp.policy[EXPORT-LO]')!.children.map((c) => c.path)).toContain('rp.policy[EXPORT-LO]/node[20]')
    expect(extrasFromGraph([{ id: 'interface[Gi0/0/1]', kind: 'object', schema: 'interface' }], sd, m, 'bgp')).toEqual([])
  })
})

describe('接口映射表', () => {
  it('主接口、同名预填、手动修改与传给后端的映射', () => {
    expect(mainInterfaces(['GE0/2/10', 'GE0/2/2', 'GE0/2/2.101', 'LoopBack0'])).toEqual(['GE0/2/2', 'GE0/2/10', 'LoopBack0'])
    let rows = initialRows(['GE0/2/1', 'LoopBack0'], ['GigabitEthernet0/0/1', 'loopback0'])
    expect(rows).toEqual([{ a: 'GE0/2/1', b: '', how: 'none' }, { a: 'LoopBack0', b: 'loopback0', how: 'same' }])
    rows = setRow(rows, 'GE0/2/1', 'GigabitEthernet0/0/1')
    expect(rows[0].how).toBe('manual')
    // 只差大小写的也传（翻译时 Loopback0 → LoopBack0 要改名，REQ-055-35）；完全同名的不传
    expect(toInterfaceMap(rows)).toEqual({ 'GE0/2/1': 'GigabitEthernet0/0/1', LoopBack0: 'loopback0' })
    expect(toInterfaceMap([{ a: 'LoopBack0', b: 'LoopBack0', how: 'same' }])).toEqual({})
    expect(setRow(rows, 'GE0/2/1', '')[0].how).toBe('none')
  })
  it('解析 CSV 与 CLI 两列格式', () => {
    const r = parseMapCsv('﻿a,b\r\n# 注释\nGE0/2/1,Gi0/0/1\n"Eth-Trunk1";"Port-channel1"\nGE0/2/2 = Gi0/0/2\nGE0/2/3\tGi0/0/3\nGE0/2/4 Gi0/0/4\nbad\n')
    expect(r.pairs).toEqual([
      ['GE0/2/1', 'Gi0/0/1'], ['Eth-Trunk1', 'Port-channel1'], ['GE0/2/2', 'Gi0/0/2'], ['GE0/2/3', 'Gi0/0/3'], ['GE0/2/4', 'Gi0/0/4'],
    ])
    expect(r.bad).toEqual([8])
  })
  it('导入合并与导出', () => {
    const rows = mergePairs(initialRows(['GE0/2/1'], []), [['ge0/2/1', 'Gi0/0/1'], ['GE0/2/9', 'Gi0/0/9']])
    expect(rows).toEqual([{ a: 'GE0/2/1', b: 'Gi0/0/1', how: 'manual' }, { a: 'GE0/2/9', b: 'Gi0/0/9', how: 'manual' }])
    expect(mapCsvRows(rows)).toEqual([['a', 'b'], ['GE0/2/1', 'Gi0/0/1'], ['GE0/2/9', 'Gi0/0/9']])
  })
})

describe('对比对象与 URL 参数', () => {
  it('同一设备两个版本', () => {
    const r = fromQuery({ a: '12', av: '12', bv: '17' })!
    expect(r.complete).toBe(true)
    expect(r.setup.mode).toBe('versions')
    expect(compareBody(r.setup)).toEqual({
      a: { device_id: 12, version_id: 12 }, b: { device_id: 12, version_id: 17 }, include_raw: false, rename_threshold: 1, hide_identity: false,
    })
    expect(toQuery(r.setup)).toEqual({ a: '12', mode: 'versions', av: '12', bv: '17' })
  })
  it('两台设备与选项', () => {
    const r = fromQuery({ a: '12', b: '14', domain: 'bgp', raw: '1', hide: '1', th: '0.8' })!
    expect(r.setup.mode).toBe('devices')
    expect(r.complete).toBe(true)
    const body = compareBody(r.setup, { 'GE0/2/1': 'Gi0/0/1' })
    expect(body).toEqual({
      a: { device_id: 12 }, b: { device_id: 14 }, include_raw: true, rename_threshold: 0.8, hide_identity: true, domain: 'bgp',
      interface_map: { 'GE0/2/1': 'Gi0/0/1' },
    })
    expect(fromQuery(toQuery(r.setup))!.setup).toEqual(r.setup)
  })
  it('参数不全或无参数', () => {
    expect(fromQuery({})).toBeNull()
    expect(fromQuery({ a: 'x' })).toBeNull()
    expect(fromQuery({ a: '3' })!.complete).toBe(false)
    expect(fromQuery({ mode: 'paste' })!.setup.mode).toBe('paste')
    expect(fromQuery({ th: '5', a: '1', b: '2' })!.setup.opts.threshold).toBe(1)
  })
  it('粘贴模式与就绪判断、交换', () => {
    const s: Setup = { mode: 'paste', a: { ...emptySide(), text: 'x', profile: 'p1' }, b: { ...emptySide(), text: 'y' }, opts: defaultOptions() }
    expect(ready(s)).toBe(true)
    expect(compareBody(s).a).toEqual({ text: 'x', profile: 'p1' })
    expect(compareBody(s).b).toEqual({ text: 'y' })
    expect(toQuery(s)).toEqual({ mode: 'paste' })
    expect(swapSides(s).a.text).toBe('y')
    expect(ready({ ...s, mode: 'versions', a: { ...emptySide(), device: 1, version: 2 }, b: { ...emptySide(), version: 2 } })).toBe(false)
  })
  it('报告文件名', () => {
    expect(dispositionName('attachment; filename="compare-A-B.zh-CN.html"')).toBe('compare-A-B.zh-CN.html')
    expect(dispositionName("attachment; filename*=UTF-8''check-%E8%AE%BE%E5%A4%87.en.md")).toBe('check-设备.en.md')
    expect(dispositionName(null)).toBe('')
    expect(reportName('PE-ASR920-01@12', 'PE 2', 'en', 'md')).toBe('compare-PE-ASR920-01@12-PE_2.en.md')
  })
})

describe('显示风格与隐藏配置（REQ-026 / REQ-028）', async () => {
  const { Terms } = await import('@/terms/terms')
  const golden = (await import('@/terms/golden.json')).default as unknown as {
    terms: ConstructorParameters<typeof Terms>[0]
    schema: { ids: string[]; keyNames: Record<string, string[]> }
  }
  const terms = new Terms(golden.terms, { ids: new Set(golden.schema.ids), keyNames: new Map(Object.entries(golden.schema.keyNames)), semantic: new Map() })
  const hw = (n: string) => terms.describeParts(n, 'huawei')
  const cs = (n: string) => terms.describeParts(n, 'cisco')
  const rows = buildRows(result)

  it('主副行按风格的命令写法；层数对不上时退回编号', async () => {
    const { segLabels } = await import('./logic')
    expect(describeNode('vrf.instance[RAN-2G]/af[ipv4]/rt[value=64512:1,direction=import]', 'object', hw))
      .toEqual({ o: 'vpn-target 64512:1 import-extcommunity', a: 'ip vpn-instance RAN-2G › ipv4-family' })
    expect(describeNode('vrf.instance[RAN-2G]/af[ipv4]/rt[value=64512:1,direction=import]', 'object', cs))
      .toEqual({ o: 'route-target import 64512:1', a: 'vrf definition RAN-2G › address-family ipv4' })
    expect(describeNode('interface[Gi0/0/0]/mtu', 'attr', cs)).toEqual({ o: 'interface Gi0/0/0', a: 'mtu' })
    expect(segLabels('a[1]/b', () => ['x'])).toEqual(['a 1', 'b'])
  })
  it('搜索也匹配命令写法', () => {
    const f = { type: '' as const, domain: '', q: 'route-map export-lo', showNa: false }
    expect(filterRows(rows, f, cs).map((r) => r.id)).toEqual(['d3', 'd4'])
    expect(filterRows(rows, f, hw)).toHaveLength(0)
  })
  it('隐藏配置标记：一侧默认值标 default，只差在默认值的项折叠', async () => {
    const { defaultOnly, hiddenKind } = await import('./logic')
    expect(rows.map(hiddenKind)).toEqual(['', '', '', '', 'default', 'default'])
    expect(rows.map(defaultOnly)).toEqual([false, false, false, false, false, true])
    const both = buildRows({ ...result, default_only: [], diffs: [diff({ a: { node: 'x', value: 1, origin: 'default', lines: [] }, b: null })] })
    expect(defaultOnly(both[0])).toBe(true)
    expect(filterRows(both, { type: '', domain: '', q: '', showNa: false })).toHaveLength(0)
    expect(groupRows([], both, false)).toEqual([])
    const derived = buildRows({ ...result, default_only: [], diffs: [diff({ a: { node: 'x', value: 1, origin: 'derived', lines: [] } })] })
    expect(hiddenKind(derived[0])).toBe('derived')
  })
  it('差异图节点用风格写法，改名两侧各自写，带隐藏配置标记', () => {
    const t = buildTree(rows, 'A ⇢ B', [], cs)
    expect(t.byKey.get('routing-policy|rp.policy[EXPORT-LO]')!.label).toBe('route-map EXPORT-LOOPBACK ⇢ route-map EXPORT-LO')
    expect(t.byKey.get('vrf|vrf.instance[RAN-2G]')!.label).toBe('vrf definition RAN-2G')
    expect(t.byKey.get('routing-policy|rp.policy[EXPORT-LO]/node[10]/action')!.hid).toBe('default')
    const lay = layoutTree(t, { side: 'both', collapsed: new Set() })
    expect(lay.nodes.find((n) => n.path === 'rp.policy[EXPORT-LO]/node[10]/action')!.hid).toBe('default')
    expect(buildTree(rows, 'A ⇢ B', [], hw).byKey.get('vrf|vrf.instance[RAN-2G]')!.label).toBe('ip vpn-instance RAN-2G')
  })
})
