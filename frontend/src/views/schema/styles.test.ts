import { describe, expect, it } from 'vitest'
import golden from '@/terms/golden.json'
import { Terms, type SchemaIndex, type TermsData } from '@/terms/terms'
import { styleForm, styleRows, type TermsLike } from './styles'

const g = golden as unknown as { terms: TermsData; schema: { ids: string[]; keyNames: Record<string, string[]> } }
const idx: SchemaIndex = { ids: new Set(g.schema.ids), keyNames: new Map(Object.entries(g.schema.keyNames)), semantic: new Map() }
const raw = new Terms(g.terms, idx)
const t: TermsLike = {
  template: (id, s) => raw.template(id, s),
  name: (id, s) => raw.name(id, s, 'zh-CN'),
  attr: (id, s) => raw.attr(id, s),
}

describe('Schema 节点的两种风格写法', () => {
  it('对象：模板与叫法，当前风格排在前面', () => {
    const rows = styleRows(t, 'vrf.instance', 'object', 'cisco')
    expect(rows.map((r) => [r.style, r.form, r.name, r.current])).toEqual([
      ['cisco', 'vrf definition {name}', 'VRF', true],
      ['huawei', 'ip vpn-instance {name}', 'VPN 实例', false],
    ])
  })
  it('属性：关键字；没有登记时不列出', () => {
    expect(styleRows(t, 'bgp.peer.remote_as', 'asn', 'huawei').map((r) => r.form)).toEqual(['as-number', 'remote-as'])
    expect(styleRows(t, 'interface.description', 'text', 'huawei')).toEqual([])
  })
  it('列表小字：当前风格的写法', () => {
    expect(styleForm(t, 'rp.policy', 'object', 'huawei')).toBe('route-policy {name}')
    expect(styleForm(t, 'rp.policy', 'object', 'cisco')).toBe('route-map {name}')
    expect(styleForm(t, 'no.such', 'string', 'cisco')).toBe('')
  })
})
