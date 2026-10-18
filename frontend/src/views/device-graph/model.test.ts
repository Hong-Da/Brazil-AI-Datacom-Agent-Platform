import { describe, expect, it } from 'vitest'
import {
  aggregateEdges, autoExpand, buildModel, collapseSubtree, domainResolver, expandSubtree, formatValue,
  highlightLines, lineRanges, nodeDeps, nodeLabel, searchNodes, splitLines, stepLine, visibleRep, visibleTree,
  MORE_PREFIX,
} from './model'
import type { ApiEdge, ApiNode, GraphData } from './types'

const SCHEMA = [
  { domain: 'interface', nodes: [{ id: 'interface' }, { id: 'interface.mtu' }, { id: 'bridge_domain' }] },
  { domain: 'vrf', nodes: [{ id: 'vrf.instance' }] },
  { domain: 'routing-policy', nodes: [{ id: 'rp.route_policy' }] },
]
const ORDER = SCHEMA.map((d) => d.domain)
const domainOf = domainResolver(SCHEMA)

function n(id: string, kind: string, extra: Partial<ApiNode> = {}): ApiNode {
  return { id, kind, schema: null, origin: 'explicit', lines: [], cards: [], ...extra }
}
const c = (from: string, to: string): ApiEdge => ({ from, to, kind: 'contains', note: '' })

/** 与演示后端 LAB-ATN-09 同形的小图，再加一个 VRF、一条引用边和一行对象内原文。 */
function sample(): GraphData {
  const I = 'interface[GE0/2/1]'
  return {
    device: 'LAB-ATN-09', profile: 'huawei-atn-v800r025', kb_version: '0.1.0',
    nodes: [
      n('device', 'device', { value: 'LAB-ATN-09' }),
      n('raw[1]', 'raw', { lines: [1], text: 'sysname LAB-ATN-09' }),
      n(I, 'object', { schema: 'interface', lines: [3], key: 'GE0/2/1' }),
      n('unknown[4]', 'unknown', { lines: [4], text: 'mtu notanumber' }),
      n(`${I}/description`, 'attr', { schema: 'interface.description', lines: [5], value: 'lab' }),
      n(`${I}/mtu`, 'attr', { schema: 'interface.mtu', origin: 'default', value: 1500 }),
      n(`${I}/vrf`, 'attr', { schema: 'interface.vrf', lines: [6], value: 'A' }),
      n('raw[7]', 'raw', { lines: [7], text: ' statistic enable' }),
      n('vrf.instance[A]', 'object', { schema: 'vrf.instance', lines: [9, 10], key: 'A' }),
      n('vrf.instance[A]/ext[x@10]', 'ext', { schema: 'ext:huawei-vrp8.apply-label', lines: [10], value: { mode: 'per-instance' } }),
    ],
    edges: [
      c('device', 'raw[1]'), c('device', I), c(I, 'unknown[4]'), c(I, `${I}/description`), c(I, `${I}/mtu`),
      c(I, `${I}/vrf`), c(I, 'raw[7]'), c('device', 'vrf.instance[A]'), c('vrf.instance[A]', 'vrf.instance[A]/ext[x@10]'),
      { from: `${I}/vrf`, to: 'vrf.instance[A]', kind: 'reference', note: 'binds VRF' },
    ],
    dangling: [],
    summary: { nodes: 10, edges: 10, kinds: {}, attr_origins: {}, edge_kinds: {}, dangling: 0 },
    text: 'sysname LAB-ATN-09\n#\ninterface GE0/2/1\n mtu notanumber\n description lab\n ip binding vpn-instance A\n statistic enable\n#\nip vpn-instance A\n apply-label per-instance\nreturn\n',
  }
}

const base = { showDefault: false, domain: '' }

describe('值与名字', () => {
  it('formatValue 处理各种取值', () => {
    expect(formatValue(null)).toBe('—')
    expect(formatValue(['a', 'b'])).toBe('a, b')
    expect(formatValue({ value: '1:1', direction: 'export' })).toBe('value=1:1, direction=export')
    expect(formatValue(false)).toBe('false')
  })
  it('nodeLabel 按类型取名', () => {
    expect(nodeLabel(n('vrf.instance[A]/af[ipv4]/rt[x]', 'object', { schema: 'vrf.instance.af.rt', key: { value: '1:1', direction: 'export' } }))).toBe('rt 1:1 export')
    expect(nodeLabel(n('a/b/label_mode', 'attr', { schema: 'vrf.instance.af.label_mode' }))).toBe('label_mode')
    expect(nodeLabel(n('x/ext[c@1]', 'ext', { schema: 'ext:cisco-iosxe.maximum-paths-eibgp' }))).toBe('maximum-paths-eibgp')
    expect(nodeLabel(n('ext[c@51]', 'ext', { schema: 'ext:cisco-iosxe.interface.19' }))).toBe('interface')
    expect(nodeLabel(n('ext[c@5]', 'ext', { schema: 'ext:huawei-vrp8.description~3' }))).toBe('description')
    expect(nodeLabel(n('raw[3]', 'raw', { text: '  version 15.2' }))).toBe('version 15.2')
  })
  it('domainResolver 用 Schema 前缀映射功能域', () => {
    expect(domainOf('rp.route_policy.node')).toBe('routing-policy')
    expect(domainOf('bridge_domain')).toBe('interface')
    expect(domainOf('ext:x.y')).toBeNull()
    expect(domainOf('nope.x')).toBeNull()
  })
})

describe('buildModel', () => {
  it('设备下插入功能域分组，raw 排最后', () => {
    const m = buildModel(sample(), domainOf, { domainOrder: ORDER })
    expect(m.domains).toEqual(['interface', 'vrf', 'raw'])
    expect(m.nodes.get('device')!.children).toEqual(['domain:interface', 'domain:vrf', 'domain:raw'])
    expect(m.nodes.get('raw[1]')!.parent).toBe('domain:raw')
    // ext 跟随父对象的功能域
    expect(m.nodes.get('vrf.instance[A]/ext[x@10]')!.domain).toBe('vrf')
  })
  it('子节点按首行排序，未识别行向上标记', () => {
    const m = buildModel(sample(), domainOf, { domainOrder: ORDER })
    const I = 'interface[GE0/2/1]'
    expect(m.nodes.get(I)!.children).toEqual(['unknown[4]', `${I}/description`, `${I}/vrf`, 'raw[7]', `${I}/mtu`])
    expect(m.nodes.get(I)!.hasUnknown).toBe(true)
    expect(m.nodes.get('domain:interface')!.hasUnknown).toBe(true)
    expect(m.nodes.get('domain:vrf')!.hasUnknown).toBe(false)
    expect(m.nodes.get('device')!.size).toBe(12)
  })
  it('groupRaw 把对象下的原文收进 raw ×N 组', () => {
    const m = buildModel(sample(), domainOf, { domainOrder: ORDER, groupRaw: true })
    const g = m.nodes.get('rawgroup:interface[GE0/2/1]')!
    expect(g.label).toBe('raw ×1')
    expect(g.lines).toEqual([7])
    expect(m.nodes.get('raw[7]')!.parent).toBe(g.id)
    // 顶层原文不分组
    expect(m.nodes.has('rawgroup:domain:raw')).toBe(false)
    // 行仍然归属真实的原文节点
    expect(m.lineOwner.get(7)).toBe('raw[7]')
  })
  it('行号映射取最深节点，并区分原文与未识别', () => {
    const m = buildModel(sample(), domainOf, { domainOrder: ORDER })
    expect(m.lineOwner.get(3)).toBe('interface[GE0/2/1]')
    expect(m.lineOwner.get(10)).toBe('vrf.instance[A]/ext[x@10]')
    expect(m.lineOwner.get(9)).toBe('vrf.instance[A]')
    expect([...m.rawLines].sort()).toEqual([1, 7])
    expect(m.unknownLines).toEqual([4])
  })
  it('父节点被筛掉的节点挂到设备下', () => {
    const d = sample()
    d.edges = d.edges.filter((e) => e.to !== 'raw[7]')
    const m = buildModel(d, domainOf, { domainOrder: ORDER })
    expect(m.nodes.get('raw[7]')!.parent).toBe('domain:raw')
  })
})

describe('可见部分', () => {
  it('默认节点隐藏，可切换显示', () => {
    const m = buildModel(sample(), domainOf, { domainOrder: ORDER })
    const all = new Set(m.nodes.keys())
    const ids = (show: boolean) => visibleTree(m, { ...base, showDefault: show, expanded: all }).map((v) => v.id)
    expect(ids(false)).not.toContain('interface[GE0/2/1]/mtu')
    expect(ids(true)).toContain('interface[GE0/2/1]/mtu')
  })
  it('收起的节点给出隐藏的后代数', () => {
    const m = buildModel(sample(), domainOf, { domainOrder: ORDER })
    const v = visibleTree(m, { ...base, expanded: new Set(['device']) })
    expect(v.map((x) => x.id)).toEqual(['device', 'domain:interface', 'domain:vrf', 'domain:raw'])
    expect(v[1]).toMatchObject({ expandable: true, expanded: false, hidden: 6 })
  })
  it('功能域筛选只保留该域', () => {
    const m = buildModel(sample(), domainOf, { domainOrder: ORDER })
    const v = visibleTree(m, { ...base, domain: 'vrf', expanded: new Set(m.nodes.keys()) })
    expect(v.map((x) => x.id)).toEqual(['device', 'domain:vrf', 'vrf.instance[A]', 'vrf.instance[A]/ext[x@10]'])
  })
  it('子节点超过上限时收进“更多”节点', () => {
    const m = buildModel(sample(), domainOf, { domainOrder: ORDER })
    const v = visibleTree(m, { ...base, expanded: new Set(m.nodes.keys()), defaultLimit: 2 })
    const more = v.find((x) => x.id === `${MORE_PREFIX}interface[GE0/2/1]`)
    expect(more?.more).toEqual({ parent: 'interface[GE0/2/1]', count: 2 })
    const v2 = visibleTree(m, { ...base, expanded: new Set(m.nodes.keys()), defaultLimit: 2, limits: new Map([['interface[GE0/2/1]', 10]]) })
    expect(v2.some((x) => x.id === `${MORE_PREFIX}interface[GE0/2/1]`)).toBe(false)
  })
  it('expandSubtree / collapseSubtree', () => {
    const m = buildModel(sample(), domainOf, { domainOrder: ORDER })
    const e = expandSubtree(m, 'domain:interface', new Set(['device']), base)
    expect(e.has('interface[GE0/2/1]')).toBe(true)
    const c2 = collapseSubtree(m, 'domain:interface', e)
    expect(c2.has('interface[GE0/2/1]')).toBe(false)
    expect(c2.has('device')).toBe(true)
  })
  it('依赖边聚合到可见祖先，并标出与选中节点相关的边', () => {
    const m = buildModel(sample(), domainOf, { domainOrder: ORDER })
    const kinds = new Set(['reference'])
    const vis = new Set(visibleTree(m, { ...base, expanded: new Set(['device']) }).map((v) => v.id))
    expect(visibleRep(m, 'interface[GE0/2/1]/vrf', vis)).toBe('domain:interface')
    const agg = aggregateEdges(m, vis, kinds, 'interface[GE0/2/1]/vrf')
    expect(agg).toHaveLength(1)
    expect(agg[0]).toMatchObject({ source: 'domain:interface', target: 'domain:vrf', count: 1, hot: true, notes: ['binds VRF'] })
    expect(aggregateEdges(m, vis, new Set(['mutex']), null)).toHaveLength(0)
    expect(nodeDeps(m, 'vrf.instance[A]').in).toHaveLength(1)
  })
  it('三语说明聚合时去重，空说明不计入', () => {
    const g = sample()
    const N = { 'zh-CN': '接口引用 VRF', en: 'Interface references the VRF', 'pt-BR': 'A interface referencia a VRF' }
    const I = 'interface[GE0/2/1]'
    g.edges = g.edges.filter((e) => e.kind === 'contains')
    g.edges.push(
      { from: `${I}/vrf`, to: 'vrf.instance[A]', kind: 'reference', note: N },
      { from: `${I}/description`, to: 'vrf.instance[A]', kind: 'reference', note: { ...N } },
      { from: `${I}/mtu`, to: 'vrf.instance[A]', kind: 'reference', note: {} },
    )
    const m = buildModel(g, domainOf, { domainOrder: ORDER })
    const vis = new Set(visibleTree(m, { ...base, showDefault: true, expanded: new Set(['device']) }).map((v) => v.id))
    const agg = aggregateEdges(m, vis, new Set(['reference']), null)
    expect(agg).toHaveLength(1)
    expect(agg[0].notes).toEqual([N])
  })
  it('搜索名字、取值和 id', () => {
    const m = buildModel(sample(), domainOf, { domainOrder: ORDER })
    expect(searchNodes(m, 'notanumber')).toEqual(['unknown[4]'])
    expect(searchNodes(m, 'GE0/2/1')).toContain('interface[GE0/2/1]')
    expect(searchNodes(m, '  ')).toEqual([])
  })
})

describe('配置行', () => {
  it('splitLines 去掉末尾换行并兼容 CRLF', () => {
    expect(splitLines('a\r\nb\n')).toEqual(['a', 'b'])
    expect(splitLines('a\n\nb')).toEqual(['a', '', 'b'])
    expect(splitLines(null)).toEqual([])
  })
  it('lineRanges 合并连续行', () => {
    expect(lineRanges([7, 1, 2, 3, 3])).toEqual([[1, 3], [7, 7]])
  })
  it('stepLine 循环跳转', () => {
    expect(stepLine([4, 9, 20], null, 1)).toBe(4)
    expect(stepLine([4, 9, 20], 9, 1)).toBe(20)
    expect(stepLine([4, 9, 20], 20, 1)).toBe(4)
    expect(stepLine([4, 9, 20], 4, -1)).toBe(20)
    expect(stepLine([], 4, -1)).toBeNull()
  })
  it('highlightLines：功能域取子树的行，设备不高亮', () => {
    const m = buildModel(sample(), domainOf, { domainOrder: ORDER })
    expect([...highlightLines(m, 'domain:vrf')].sort((a, b) => a - b)).toEqual([9, 10])
    expect(highlightLines(m, 'device').size).toBe(0)
    expect([...highlightLines(m, 'interface[GE0/2/1]')]).toEqual([3])
  })
})

describe('大图', () => {
  /** 约 2500 节点：140 个接口 × (8 属性 + 6 原文) + 1000 行顶层原文。 */
  function big(): GraphData {
    const nodes: ApiNode[] = [n('device', 'device', { value: 'BIG' })]
    const edges: ApiEdge[] = []
    let line = 1
    for (let i = 0; i < 140; i++) {
      const o = `interface[GE${i}]`
      nodes.push(n(o, 'object', { schema: 'interface', key: `GE${i}`, lines: [line++] }))
      edges.push(c('device', o))
      for (let j = 0; j < 8; j++) {
        nodes.push(n(`${o}/a${j}`, 'attr', { schema: 'interface.mtu', lines: [line++], value: j }))
        edges.push(c(o, `${o}/a${j}`))
      }
      for (let j = 0; j < 6; j++) {
        nodes.push(n(`raw[${line}]`, 'raw', { lines: [line], text: 'x' }))
        edges.push(c(o, `raw[${line++}]`))
      }
    }
    for (let k = 0; k < 1000; k++) {
      nodes.push(n(`raw[${line}]`, 'raw', { lines: [line], text: 'y' }))
      edges.push(c('device', `raw[${line++}]`))
    }
    return { device: 'BIG', profile: null, kb_version: null, nodes, edges, dangling: [], summary: { nodes: nodes.length, edges: edges.length, kinds: {}, attr_origins: {}, edge_kinds: {}, dangling: 0 }, text: null }
  }
  it('首屏按预算展开，只渲染一小部分', () => {
    const m = buildModel(big(), domainOf, { domainOrder: ORDER, groupRaw: true })
    expect(m.nodes.size).toBeGreaterThan(2500)
    const expanded = autoExpand(m, base, 80)
    const v = visibleTree(m, { ...base, expanded })
    expect(v.length).toBeLessThanOrEqual(80)
    expect(v.map((x) => x.id)).toEqual(['device', 'domain:interface', 'domain:raw'])
  })
  it('展开 1000 行的 raw 功能域时按上限分页', () => {
    const m = buildModel(big(), domainOf, { domainOrder: ORDER })
    const v = visibleTree(m, { ...base, expanded: new Set(['device', 'domain:raw']), defaultLimit: 120 })
    expect(v.length).toBe(1 + 2 + 120 + 1)
    expect(v[v.length - 1].more?.count).toBe(880)
  })
  it('展开选中子树受上限约束', () => {
    const m = buildModel(big(), domainOf, { domainOrder: ORDER, groupRaw: true })
    const e = expandSubtree(m, 'domain:interface', new Set(['device']), base, 300)
    const v = visibleTree(m, { ...base, expanded: e, defaultLimit: 1000 })
    expect(e.has('domain:interface')).toBe(true)
    expect(v.length).toBeLessThan(400)
  })
})
