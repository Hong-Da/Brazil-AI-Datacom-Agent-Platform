/**
 * 显示风格：TypeScript 版与 Python 版（lmesh.core.terms）结果一致。
 * golden.json 由 scripts/terms_golden.py 用 Python 版对知识库样本生成（术语表或 Schema 改动后重新生成）。
 */
import { describe, expect, it } from 'vitest'
import golden from './golden.json'
import { Terms, splitNodeId, toStyle, type SchemaIndex, type TermsData } from './terms'

const g = golden as unknown as {
  terms: TermsData
  schema: { ids: string[]; keyNames: Record<string, string[]> }
  labels: { schema: string; key: unknown; huawei: string; cisco: string; nokia: string }[]
  describes: { id: string; huawei: string; cisco: string; nokia: string }[]
  contexts: { schema: string; key: unknown; attrs: Record<string, unknown>; huawei: string[]; cisco: string[]; nokia: string[] }[]
}
const STY = ['huawei', 'cisco', 'nokia'] as const
const idx: SchemaIndex = { ids: new Set(g.schema.ids), keyNames: new Map(Object.entries(g.schema.keyNames)), semantic: new Map() }
const t = new Terms(g.terms, idx)

describe('术语渲染（与 tests/unit/test_terms.py 相同的例子）', () => {
  it.each([
    ['vrf.instance', 'RAN', 'ip vpn-instance RAN', 'vrf definition RAN'],
    ['bgp.af', { afi: 'ipv4', vrf: 'RAN' }, 'ipv4-family vpn-instance RAN', 'address-family ipv4 vrf RAN'],
    ['bgp.af', { afi: 'ipv4', vrf: '' }, 'ipv4-family unicast', 'address-family ipv4'],
    ['vrf.instance.af.rt', { value: '1:1', direction: 'export' }, 'vpn-target 1:1 export-extcommunity', 'route-target export 1:1'],
    ['rp.prefix_list', 'LO', 'ip ip-prefix LO', 'ip prefix-list LO'],
    ['mgmt.line', { type: 'vty', range: '0 4' }, 'user-interface vty 0 4', 'line vty 0 4'],
  ])('%s %j', (schema, key, hw, cs) => {
    expect(t.label(schema, key, 'huawei')).toBe(hw)
    expect(t.label(schema, key, 'cisco')).toBe(cs)
  })

  it('规范编号 → 命令路径', () => {
    const nid = 'bgp.instance[65000]/bgp.af[afi=ipv4,vrf=]/peer[RR]/export_policy'
    expect(t.describe(nid, 'huawei')).toBe('bgp 65000 › ipv4-family unicast › peer RR › route-policy … export')
    expect(t.describe(nid, 'cisco')).toBe('router bgp 65000 › address-family ipv4 › neighbor RR › route-map … out')
    expect(splitNodeId('interface[GigabitEthernet0/2/1]/ospf[_]/cost')).toEqual([
      ['interface', 'GigabitEthernet0/2/1'], ['ospf', '_'], ['cost', null],
    ])
    expect(t.describe('interface[Gi0/0/1]/ospf[_]/cost', 'cisco')).toBe('interface Gi0/0/1 › ip ospf › ip ospf cost')
  })

  it('未知风格按华为；未登记的对象用最后一段 + 键', () => {
    expect(toStyle('juniper')).toBe('huawei')
    expect(t.label('no.such', 'X', 'cisco')).toMatch(/^such X/)
    expect(t.attr('no.such', 'huawei')).toBeNull()
    expect(t.template('vrf.instance', 'cisco')).toBe('vrf definition {name}')
    expect(t.template('static.route', 'huawei')).toBe('ip route-static vpn-instance {vrf} {prefix} {nexthop} | ip route-static {prefix} {nexthop}')
  })
})

describe('与 Python 版逐条一致（知识库样本建图的全部节点）', () => {
  it(`对象命令写法 ${g.labels.length} 条`, () => {
    const bad = g.labels.filter((c) => STY.some((s) => t.label(c.schema, c.key, s) !== c[s]))
    expect(bad.slice(0, 5)).toEqual([])
  })
  it(`命令路径 ${g.describes.length} 条`, () => {
    const bad = g.describes.filter((c) => STY.some((s) => t.describe(c.id, s) !== c[s]))
    expect(bad.slice(0, 5)).toEqual([])
  })
  it(`顶层对象的配置上下文 ${g.contexts.length} 条（M7-5）`, () => {
    const bad = g.contexts.filter((c) => STY.some((s) => JSON.stringify(t.context(c.schema, c.key, c.attrs, s)) !== JSON.stringify(c[s])))
    expect(bad.slice(0, 5)).toEqual([])
    expect(g.contexts.some((c) => c.nokia.join(' › ') === 'service › vprn VPRN-3001')).toBe(true)
  })
})

describe('Nokia 风格（M7-5）', () => {
  it('端口、LAG、路由器接口的写法不同；未登记的属性按华为显示', () => {
    expect(t.label('interface', '1/1/4', 'nokia')).toBe('port 1/1/4')
    expect(t.label('interface', 'lag-1', 'nokia')).toBe('lag-1')
    expect(t.label('interface', 'to-CE1', 'nokia')).toBe('interface "to-CE1"')
    expect(t.label('vrf.instance.af.rt', { value: '1:1', direction: 'both' }, 'nokia')).toBe('vrf-target target:1:1')
    expect(t.label('vrf.instance.af.rt', { value: '1:1', direction: 'import' }, 'nokia')).toBe('vrf-target import target:1:1')
    expect(toStyle('nokia')).toBe('nokia')
    expect(t.attr('interface.access.qos_in', 'nokia')).toBe('ingress qos')
    expect(t.context('interface', 'system', {}, 'nokia')).toEqual(['router Base'])
    expect(t.context('interface', 'system', {}, 'huawei')).toEqual([])
  })
})
