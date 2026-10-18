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
  labels: { schema: string; key: unknown; huawei: string; cisco: string }[]
  describes: { id: string; huawei: string; cisco: string }[]
}
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
    const bad = g.labels.filter((c) => t.label(c.schema, c.key, 'huawei') !== c.huawei || t.label(c.schema, c.key, 'cisco') !== c.cisco)
    expect(bad.slice(0, 5)).toEqual([])
  })
  it(`命令路径 ${g.describes.length} 条`, () => {
    const bad = g.describes.filter((c) => t.describe(c.id, 'huawei') !== c.huawei || t.describe(c.id, 'cisco') !== c.cisco)
    expect(bad.slice(0, 5)).toEqual([])
  })
})
