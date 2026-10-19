/** 视图层级（REQ-026）与关系图谱数据（REQ-027）。 */
import { describe, expect, it } from 'vitest'
import { autoExpand, buildModel, domainResolver, visibleTree } from './model'
import { buildForce, domainColorVar, domainCounts, dotSize } from './force'
import { Terms } from '@/terms/terms'
import golden from '@/terms/golden.json'
import type { ApiEdge, ApiNode, GraphData } from './types'

const SCHEMA = [
  { domain: 'interface', nodes: [{ id: 'interface' }] },
  { domain: 'vrf', nodes: [{ id: 'vrf.instance' }] },
  { domain: 'bgp', nodes: [{ id: 'bgp.instance' }, { id: 'bgp.af' }, { id: 'bgp.peer' }] },
]
const domainOf = domainResolver(SCHEMA)
const ORDER = SCHEMA.map((d) => d.domain)

function n(id: string, kind: string, extra: Partial<ApiNode> = {}): ApiNode {
  return { id, kind, schema: null, origin: 'explicit', lines: [], cards: [], ...extra }
}
const c = (from: string, to: string): ApiEdge => ({ from, to, kind: 'contains', note: '' })

const B = 'bgp.instance[65000]'
const AF = `${B}/af[afi=vpnv4,vrf=]`
const PEER = `${AF}/peer[10.0.0.1]`
function sample(): GraphData {
  return {
    device: 'PE-1', profile: 'huawei-atn-v800r025', kb_version: '0.2.0',
    nodes: [
      n('device', 'device', { value: 'PE-1' }),
      n('raw[1]', 'raw', { lines: [1], text: 'sysname PE-1' }),
      n('interface[Lo0]', 'object', { schema: 'interface', key: 'Lo0', lines: [3] }),
      n('interface[Lo0]/mtu', 'attr', { schema: 'interface.mtu', origin: 'default', value: 1500 }),
      n('interface[Lo0]/vrf', 'attr', { schema: 'interface.vrf', value: 'A', lines: [4] }),
      n('vrf.instance[A]', 'object', { schema: 'vrf.instance', key: 'A', lines: [6] }),
      n('vrf.instance[B]', 'object', { schema: 'vrf.instance', key: 'B', origin: 'default' }),
      n(B, 'object', { schema: 'bgp.instance', key: '65000', lines: [8] }),
      n(AF, 'object', { schema: 'bgp.af', key: { afi: 'vpnv4', vrf: '' }, lines: [9] }),
      n(PEER, 'object', { schema: 'bgp.af.peer', key: '10.0.0.1', lines: [10] }),
      n(`${PEER}/enabled`, 'attr', { schema: 'bgp.af.peer.enabled', value: true, lines: [10] }),
      n(`${PEER}/x`, 'attr', { schema: 'bgp.af.peer.x', value: 'A', lines: [11], origin: 'default' }),
    ],
    edges: [
      c('device', 'raw[1]'), c('device', 'interface[Lo0]'), c('interface[Lo0]', 'interface[Lo0]/mtu'), c('interface[Lo0]', 'interface[Lo0]/vrf'),
      c('device', 'vrf.instance[A]'), c('device', 'vrf.instance[B]'), c('device', B), c(B, AF), c(AF, PEER), c(PEER, `${PEER}/enabled`), c(PEER, `${PEER}/x`),
      { from: 'interface[Lo0]/vrf', to: 'vrf.instance[A]', kind: 'reference', note: '' },
      { from: 'interface[Lo0]/vrf', to: 'vrf.instance[A]', kind: 'reference', note: 'dup' },
      { from: `${PEER}/x`, to: 'vrf.instance[B]', kind: 'reference', note: '' },
      { from: B, to: 'interface[Lo0]', kind: 'prerequisite', note: '' },
    ],
    dangling: [],
    summary: { nodes: 12, edges: 15, kinds: {}, attr_origins: {}, edge_kinds: {}, dangling: 0 },
    text: '',
  }
}

const g = golden as unknown as { terms: ConstructorParameters<typeof Terms>[0]; schema: { ids: string[]; keyNames: Record<string, string[]> } }
const terms = new Terms(g.terms, { ids: new Set(g.schema.ids), keyNames: new Map(Object.entries(g.schema.keyNames)), semantic: new Map() })
const labeler = (style: string) => (a: ApiNode) =>
  a.kind === 'object' && a.schema ? terms.label(a.schema, a.key, style) : a.kind === 'attr' && a.schema ? terms.attr(a.schema, style) : null

describe('视图层级', () => {
  it('不插入功能域，设备 → bgp 65000 → ipv4-family vpnv4 → peer 10.0.0.1', () => {
    const m = buildModel(sample(), domainOf, { domainOrder: ORDER, byDomain: false, groupRaw: true, labeler: labeler('huawei') })
    expect([...m.nodes.keys()].some((k) => k.startsWith('domain:'))).toBe(false)
    expect(m.nodes.get(PEER)!.parent).toBe(AF)
    expect(m.nodes.get(AF)!.parent).toBe(B)
    expect(m.nodes.get(B)!.parent).toBe('device')
    const path = [B, AF, PEER].map((id) => m.nodes.get(id)!.label)
    expect(path).toEqual(['bgp 65000', 'ipv4-family vpnv4', 'peer 10.0.0.1'])
    expect(m.nodes.get(`${PEER}/enabled`)!.label).toBe('peer … enable')
    // 设备下的原文收进一组；功能域仍记在节点上供筛选
    expect(m.nodes.get('raw[1]')!.parent).toBe('rawgroup:device')
    expect(m.domains).toEqual(['interface', 'vrf', 'bgp', 'raw'])
  })

  it('Cisco 风格的节点名', () => {
    const m = buildModel(sample(), domainOf, { byDomain: false, labeler: labeler('cisco') })
    expect([B, AF, PEER].map((id) => m.nodes.get(id)!.label)).toEqual(['router bgp 65000', 'address-family vpnv4', 'neighbor 10.0.0.1'])
    expect(m.nodes.get('interface[Lo0]/vrf')!.label).toBe('vrf forwarding')
  })

  it('功能域筛选作用于顶层对象', () => {
    const m = buildModel(sample(), domainOf, { domainOrder: ORDER, byDomain: false, groupRaw: true })
    const o = { showDefault: false, domain: 'bgp' }
    const vis = visibleTree(m, { ...o, expanded: autoExpand(m, o, 80) }).map((v) => v.id)
    expect(vis).toContain(PEER)
    expect(vis).not.toContain('interface[Lo0]')
    expect(vis).not.toContain('rawgroup:device')
  })

  it('功能域按节点编号判定：interface.bfd 属于 bfd，interface 仍属于 interface', () => {
    const r = domainResolver([
      { domain: 'interface', nodes: [{ id: 'interface' }, { id: 'interface.mtu' }] },
      { domain: 'bfd', nodes: [{ id: 'bfd.global' }, { id: 'interface.bfd' }, { id: 'interface.bfd.min_tx' }] },
    ])
    expect(r('interface')).toBe('interface')
    expect(r('interface.mtu')).toBe('interface')
    expect(r('interface.bfd.min_tx')).toBe('bfd')
    expect(r('interface.unknown_attr')).toBe('interface')
  })

  it('按功能域时与原来一致', () => {
    const m = buildModel(sample(), domainOf, { domainOrder: ORDER })
    expect(m.nodes.get(B)!.parent).toBe('domain:bgp')
  })
})

describe('关系图谱数据', () => {
  const m = buildModel(sample(), domainOf, { domainOrder: ORDER, byDomain: false, groupRaw: true, labeler: labeler('huawei') })

  it('每个对象一个圆点，属性归到所属对象；默认值与原文默认隐藏', () => {
    const f = buildForce(m, { showDefault: false, showRaw: false })
    expect(f.nodes.map((x) => x.id).sort()).toEqual(['interface[Lo0]', 'vrf.instance[A]', B, AF, PEER].sort())
    expect(f.owner(`${PEER}/enabled`)).toBe(PEER)
    expect(f.owner('device')).toBeNull()
    // 包含：对象之间的父子；依赖：端点归到对象后去重（两条重复的引用合成一条）
    const ids = f.edges.map((e) => e.id).sort()
    expect(ids).toEqual([
      `contains|${AF}|${PEER}`, `contains|${B}|${AF}`, `prerequisite|${B}|interface[Lo0]`, 'reference|interface[Lo0]|vrf.instance[A]',
    ].sort())
    const deg = Object.fromEntries(f.nodes.map((x) => [x.id, x.degree]))
    expect(deg[B]).toBe(2)
    expect(deg['vrf.instance[A]']).toBe(1)
  })

  it('显示默认值与原文后，默认对象和它的依赖、原文节点都出现', () => {
    const f = buildForce(m, { showDefault: true, showRaw: true })
    const ids = f.nodes.map((x) => x.id)
    expect(ids).toContain('vrf.instance[B]')
    expect(ids).toContain('raw[1]')
    expect(f.nodes.find((x) => x.id === 'vrf.instance[B]')!.origin).toBe('default')
    expect(f.edges.some((e) => e.id === `reference|${PEER}|vrf.instance[B]`)).toBe(true)
  })

  it('大小、颜色、计数', () => {
    expect(dotSize(0)).toBe(10)
    expect(dotSize(400)).toBe(40)
    expect(dotSize(4)).toBeGreaterThan(dotSize(1))
    expect(domainColorVar('vrf', ORDER)).toBe('--dom-2')
    expect(domainColorVar('raw', ORDER)).toBe('--dom-4')
    const f = buildForce(m, { showDefault: false, showRaw: false })
    expect(domainCounts(f.nodes).get('bgp')).toBe(3)
  })

  it('约 2500 个节点的大图在可接受时间内建好', () => {
    const nodes: ApiNode[] = [n('device', 'device')]
    const edges: ApiEdge[] = []
    for (let i = 0; i < 400; i++) {
      const id = `interface[GE${i}]`
      nodes.push(n(id, 'object', { schema: 'interface', key: `GE${i}`, lines: [i * 6 + 1] }))
      edges.push(c('device', id))
      for (let j = 0; j < 5; j++) {
        nodes.push(n(`${id}/a${j}`, 'attr', { schema: `interface.a${j}`, lines: [i * 6 + 2 + j] }))
        edges.push(c(id, `${id}/a${j}`))
      }
      edges.push({ from: `${id}/a0`, to: `interface[GE${(i + 1) % 400}]`, kind: 'reference', note: '' })
    }
    const data: GraphData = { device: 'X', profile: null, kb_version: null, nodes, edges, dangling: [], summary: { nodes: 0, edges: 0, kinds: {}, attr_origins: {}, edge_kinds: {}, dangling: 0 } }
    const t0 = performance.now()
    const f = buildForce(buildModel(data, domainOf, { byDomain: false }), { showDefault: false, showRaw: false })
    expect(f.nodes.length).toBe(400)
    expect(f.edges.length).toBe(400)
    expect(performance.now() - t0).toBeLessThan(1500)
  })
})

describe('Nokia 配置上下文分组（M7-5）', () => {
  const ctx = (a: ApiNode, attrs: Record<string, unknown>) => (a.schema ? terms.context(a.schema, a.key, attrs, 'nokia') : [])
  const build = (extra: Partial<Parameters<typeof buildModel>[2]> = {}) =>
    buildModel(sample(), domainOf, { domainOrder: ORDER, byDomain: false, groupRaw: true, labeler: labeler('nokia'), contextOf: ctx, ...extra })

  it('顶层对象挂到上下文分组下：VRF → service；BGP → router Base；接口绑定 VRF 时并到同名的 vprn A 下', () => {
    const m = build()
    expect(m.nodes.get('vrf.instance[A]')!.label).toBe('vprn A')
    expect(m.nodes.get('vrf.instance[A]')!.parent).toBe('ctx:service')
    // service › vprn A 分组与 vprn A 对象同名：不单独成组，接口挂到 vprn A 下
    expect(m.nodes.has('ctx:service › vprn A')).toBe(false)
    expect(m.nodes.get('interface[Lo0]')!.parent).toBe('vrf.instance[A]')
    expect(m.nodes.get(B)!.parent).toBe('ctx:router Base')
    expect(m.nodes.get(AF)!.parent).toBe(B)
    const g = m.nodes.get('ctx:service')!
    expect(g.kind).toBe('domain')
    expect(g.label).toBe('service')
    expect([...g.ctxDomains!].sort()).toEqual(['interface', 'vrf'])
    // 设备下：原文分组、service（首行 3）、router Base（首行 8），按最早的配置行排序
    expect(m.nodes.get('device')!.children).toEqual(['rawgroup:device', 'ctx:service', 'ctx:router Base'])
    expect(m.nodes.get('interface[Lo0]')!.depth).toBe(3)
  })

  it('没有同名对象时保留 service › vprn X 分组', () => {
    const d = sample()
    d.nodes = d.nodes.filter((x) => x.id !== 'vrf.instance[A]')
    d.edges = d.edges.filter((e) => e.to !== 'vrf.instance[A]' && e.from !== 'vrf.instance[A]')
    const m = buildModel(d, domainOf, { byDomain: false, labeler: labeler('nokia'), contextOf: ctx })
    expect(m.nodes.get('interface[Lo0]')!.parent).toBe('ctx:service › vprn A')
    expect(m.nodes.get('ctx:service › vprn A')!.parent).toBe('ctx:service')
  })

  it('功能域筛选：分组看子树里的功能域，分组下的顶层对象按自身功能域', () => {
    const m = build()
    const o = { showDefault: true, domain: 'bgp', expanded: new Set(['device', 'ctx:service', 'ctx:router Base']) }
    const ids = visibleTree(m, o).map((v) => v.id)
    expect(ids).toContain('ctx:router Base')
    expect(ids).toContain(B)
    expect(ids).not.toContain('ctx:service')
    const o2 = { ...o, domain: 'vrf', expanded: new Set(['device', 'ctx:service', 'vrf.instance[A]']) }
    const ids2 = visibleTree(m, o2).map((v) => v.id)
    expect(ids2).toContain('vrf.instance[A]')
    expect(ids2).not.toContain('interface[Lo0]')
  })

  it('不给 contextOf、按功能域组织或上下文为空时不插入分组', () => {
    const none = (m: ReturnType<typeof build>) => [...m.nodes.keys()].filter((k) => k.startsWith('ctx:'))
    expect(none(build({ contextOf: undefined }))).toEqual([])
    expect(none(build({ byDomain: true }))).toEqual([])
    const m = build({ contextOf: () => [] })
    expect(none(m)).toEqual([])
    expect(m.nodes.get(B)!.parent).toBe('device')
  })

  it('Nokia 写法：接口 1/1/4 显示为 port，挂在 port 分组下', () => {
    const d = sample()
    d.nodes.push(n('interface[1/1/4]', 'object', { schema: 'interface', key: '1/1/4', lines: [20] }))
    d.edges.push(c('device', 'interface[1/1/4]'))
    const m = buildModel(d, domainOf, { byDomain: false, labeler: labeler('nokia'), contextOf: ctx })
    expect(m.nodes.get('interface[1/1/4]')!.label).toBe('port 1/1/4')
    expect(m.nodes.get('interface[1/1/4]')!.parent).toBe('ctx:port')
  })
})
