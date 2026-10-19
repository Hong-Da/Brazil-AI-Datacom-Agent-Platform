import { describe, expect, it } from 'vitest'
import { buildModel } from '@/views/device-graph/model'
import { bandLayout, type FNode } from '@/views/device-graph/force'
import type { GraphData } from '@/views/device-graph/types'
import { bandGroups, chipOf, crossOf, groupKeyOf, groupLinks, layerName, ownerObject } from './layers'
import type { CrossEdge } from './types'

const N = (id: string, kind: string, schema: string | null, extra: Record<string, unknown> = {}) => ({ id, kind, schema, origin: 'explicit', lines: [], cards: [], ...extra })
const G: GraphData = {
  device: 'R1',
  profile: 'p',
  kb_version: '0',
  nodes: [
    N('device', 'device', null, { value: 'R1' }),
    N('vrf.instance[RAN]', 'object', 'vrf.instance', { key: 'RAN', lines: [3] }),
    N('vrf.instance[RAN]/af[ipv4]', 'object', 'vrf.instance.af', { key: 'ipv4', lines: [4] }),
    N('vrf.instance[RAN]/af[ipv4]/label_mode', 'attr', 'vrf.instance.af.label_mode', { origin: 'default', value: 'per-instance' }),
    N('interface[GE0/2/1]', 'object', 'interface', { key: 'GE0/2/1', lines: [7] }),
    N('interface[GE0/2/1]/vrf', 'attr', 'interface.vrf', { value: 'RAN', lines: [8] }),
    N('interface[GE0/2/1]/mtu', 'attr', 'interface.mtu', { origin: 'default', value: 1500 }),
    N('interface[GE0/2/1]/ipv4[10.1.1.1]', 'object', 'interface.ipv4', { key: '10.1.1.1', lines: [9] }),
    N('interface[GE0/2/1]/ipv4[10.1.1.1]/prefix_length', 'attr', 'interface.ipv4.prefix_length', { value: 30, lines: [9] }),
  ],
  edges: [
    ['device', 'vrf.instance[RAN]'], ['vrf.instance[RAN]', 'vrf.instance[RAN]/af[ipv4]'], ['vrf.instance[RAN]/af[ipv4]', 'vrf.instance[RAN]/af[ipv4]/label_mode'],
    ['device', 'interface[GE0/2/1]'], ['interface[GE0/2/1]', 'interface[GE0/2/1]/vrf'], ['interface[GE0/2/1]', 'interface[GE0/2/1]/mtu'],
    ['interface[GE0/2/1]', 'interface[GE0/2/1]/ipv4[10.1.1.1]'], ['interface[GE0/2/1]/ipv4[10.1.1.1]', 'interface[GE0/2/1]/ipv4[10.1.1.1]/prefix_length'],
  ].map(([from, to]) => ({ from, to, kind: 'contains', note: {} })).concat([{ from: 'interface[GE0/2/1]/vrf', to: 'vrf.instance[RAN]', kind: 'reference', note: {} }]),
  dangling: [],
  summary: { nodes: 9, edges: 9, kinds: {}, attr_origins: {}, edge_kinds: {}, dangling: 0 },
}
const LAYER: Record<string, string> = {
  'vrf.instance[RAN]': 'network',
  'vrf.instance[RAN]/af[ipv4]': 'network',
  'vrf.instance[RAN]/af[ipv4]/label_mode': 'mpls',
  'interface[GE0/2/1]': 'physical',
  'interface[GE0/2/1]/vrf': 'network',
  'interface[GE0/2/1]/mtu': 'datalink',
  'interface[GE0/2/1]/ipv4[10.1.1.1]': 'network',
  'interface[GE0/2/1]/ipv4[10.1.1.1]/prefix_length': 'network',
}
const CROSS: CrossEdge[] = [
  { from: 'interface[GE0/2/1]', to: 'vrf.instance[RAN]', kind: 'reference', from_layer: 'physical', to_layer: 'network', via: 'interface[GE0/2/1]/vrf', count: 1 },
  { from: 'interface[GE0/2/1]', to: 'interface[GE0/2/1]/ipv4[10.1.1.1]', kind: 'contains', from_layer: 'physical', to_layer: 'network', via: 'interface[GE0/2/1]', count: 1 },
]
const m = buildModel(G, (s) => s.split('.')[0], { byDomain: false })

describe('TCP/IP 分层', () => {
  it('所属对象', () => {
    expect(ownerObject(m, 'interface[GE0/2/1]/vrf')).toBe('interface[GE0/2/1]')
    expect(ownerObject(m, 'vrf.instance[RAN]')).toBe('vrf.instance[RAN]')
    expect(ownerObject(m, 'device')).toBeNull()
  })

  it('分组：同层子对象由父对象代表；作用层不同的属性单独成组；默认值按开关', () => {
    const g = bandGroups(m, LAYER, { showDefault: false })
    expect(g.get('network')?.map((x) => [x.schema, x.attr, x.items.length])).toEqual([
      ['interface.ipv4', false, 1],
      ['vrf.instance', false, 1],
      ['interface.vrf', true, 1],
    ])
    expect(g.get('network')?.find((x) => x.attr)?.ownerSchema).toBe('interface')
    expect(g.get('physical')?.map((x) => x.schema)).toEqual(['interface'])
    expect(g.has('datalink')).toBe(false)
    const withDef = bandGroups(m, LAYER, { showDefault: true })
    expect(withDef.get('datalink')?.[0].schema).toBe('interface.mtu')
    expect(withDef.get('mpls')?.[0].schema).toBe('vrf.instance.af.label_mode')
  })

  it('格子与分组键：同层子对象落到父对象，作用层不同的属性是自己', () => {
    expect(chipOf(m, LAYER, 'vrf.instance[RAN]/af[ipv4]')).toBe('vrf.instance[RAN]')
    expect(chipOf(m, LAYER, 'interface[GE0/2/1]/vrf')).toBe('interface[GE0/2/1]/vrf')
    expect(chipOf(m, LAYER, 'interface[GE0/2/1]/ipv4[10.1.1.1]/prefix_length')).toBe('interface[GE0/2/1]/ipv4[10.1.1.1]')
    expect(groupKeyOf(m, LAYER, 'vrf.instance[RAN]/af[ipv4]')).toBe('network|vrf.instance')
    expect(groupKeyOf(m, LAYER, 'interface[GE0/2/1]')).toBe('physical|interface')
  })

  it('跨层依赖：按分组汇总、按对象列出（出边在前）', () => {
    expect(groupLinks(m, LAYER, CROSS)).toEqual([
      { a: 'physical|interface', b: 'network|vrf.instance', count: 1 },
      { a: 'physical|interface', b: 'network|interface.ipv4', count: 1 },
    ])
    expect(crossOf(CROSS, 'vrf.instance[RAN]').map((x) => [x.other, x.out])).toEqual([['interface[GE0/2/1]', false]])
    expect(crossOf(CROSS, 'interface[GE0/2/1]').length).toBe(2)
    expect(crossOf(CROSS, null)).toEqual([])
  })

  it('层名按语言，缺省用编号或回退文字', () => {
    const info = [{ id: 'network', name: { 'zh-CN': '网络层', en: 'Network' } }]
    expect(layerName(info, 'network', 'zh-CN', '-')).toBe('网络层')
    expect(layerName(info, 'network', 'pt-BR', '-')).toBe('Network')
    expect(layerName(info, 'xx', 'en', '-')).toBe('xx')
    expect(layerName(info, null, 'en', 'none')).toBe('none')
  })
})

describe('按层分带布局', () => {
  const dot = (id: string, domain = 'd'): FNode => ({ id, label: id, kind: 'object', domain, origin: 'explicit', degree: 1 })
  it('带按顺序自上而下，同带的圆点在带内；不归层的放最后一条带', () => {
    const nodes = [dot('a'), dot('b'), dot('c'), dot('x')]
    const band: Record<string, string> = { a: 'network', b: 'physical', c: 'network' }
    const { pos, bands } = bandLayout(nodes, (id) => band[id] ?? null, ['network', 'physical'], 800)
    expect(bands.map((b) => b.id)).toEqual(['network', 'physical', '__other'])
    for (const [id, b] of Object.entries({ a: 0, c: 0, b: 1, x: 2 })) {
      const p = pos.get(id)!
      expect(p.y).toBeGreaterThanOrEqual(bands[b].y)
      expect(p.y).toBeLessThanOrEqual(bands[b].y + bands[b].h)
    }
    expect(bands[0].y).toBeLessThan(bands[1].y)
  })
  it('圆点多时换行，带变高', () => {
    const nodes = Array.from({ length: 40 }, (_, i) => dot(`n${i}`))
    const { bands } = bandLayout(nodes, () => 'network', ['network'], 400, { colW: 70, rowH: 40 })
    const one = bandLayout(nodes.slice(0, 3), () => 'network', ['network'], 400, { colW: 70, rowH: 40 }).bands[0]
    expect(bands[0].h).toBeGreaterThan(one.h)
  })
})
