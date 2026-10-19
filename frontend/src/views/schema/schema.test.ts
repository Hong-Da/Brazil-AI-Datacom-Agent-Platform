import { describe, expect, it } from 'vitest'
import {
  buildTree, compareGroups, coverageOf, credibilityCounts, depApplies, edgesOf, filterTree, fmtValue, shortName,
  type CompareRow, type SchemaDomain, type SchemaNode,
} from './model'
import { assignColumns, edgePath, fitText, layoutGroups, CW, PH } from './layout'
import {
  descendants, errorDetails, formToBody, isDirty, newForm, nodeToForm, rangeOf, splitList, staleFields, usageGroups, validateForm,
} from './form'
import { fieldsFor, formatOk, isAsn, isCommunity, isMask, isPrefix, isRd } from './typefields'

function node(id: string, parent: string | null, extra: Partial<SchemaNode> = {}): SchemaNode {
  return {
    id, parent, type: 'string', key: [], semantic: { 'zh-CN': id, en: id }, range: null, choices: null, ordered: false,
    ref: null, deprecated: false, replaced_by: null, status: 'draft', children: 0, ...extra,
  }
}

const DOMAINS: SchemaDomain[] = [
  {
    domain: 'bgp',
    nodes: [
      node('bgp.af', 'bgp.instance', { type: 'object' }),
      node('bgp.af.network', 'bgp.af'),
      node('bgp.instance', null, { type: 'object' }),
      node('bgp.peer', 'bgp.instance', { type: 'object' }),
      node('bgp.peer.keepalive', 'bgp.peer', { type: 'integer', range: [0, 21845] }),
      node('bgp.peer.old', 'bgp.peer', { deprecated: true, replaced_by: 'bgp.peer.keepalive' }),
    ],
    deps: [{ kind: 'cross_device', from: 'bgp.peer', to: 'interface.ipv4', note: '', profiles: [] }],
  },
  {
    domain: 'interface',
    nodes: [node('interface', null, { type: 'object' }), node('interface.ipv4', 'interface'), node('interface.vrf', 'interface', { type: 'ref', ref: 'vrf' })],
    deps: [
      { kind: 'reference', from: 'interface.vrf', to: 'vrf', note: 'n', profiles: [] },
      { kind: 'mutex', from: 'interface.l2', to: 'interface.ipv4', note: '', profiles: ['p1'] },
    ],
  },
]

describe('Schema 树', () => {
  it('短名去掉父节点前缀或公共段', () => {
    expect(shortName('interface.ipv4', 'interface')).toBe('ipv4')
    expect(shortName('bgp.af', 'bgp.instance')).toBe('af')
    expect(shortName('interface', null)).toBe('interface')
  })
  it('按 parent 先序排列并计算深度', () => {
    const [bgp] = buildTree(DOMAINS)
    expect(bgp!.items.map((i) => `${i.depth}:${i.node.id}`)).toEqual([
      '0:bgp.instance', '1:bgp.af', '2:bgp.af.network', '1:bgp.peer', '2:bgp.peer.keepalive', '2:bgp.peer.old',
    ])
    expect(bgp!.items[1]!.name).toBe('af')
  })
  it('父子成环时不丢节点', () => {
    const t = buildTree([{ domain: 'x', nodes: [node('a', 'b'), node('b', 'a')], deps: [] }])
    expect(t[0]!.items.map((i) => i.node.id).sort()).toEqual(['a', 'b'])
  })
  it('筛选去掉没有命中的功能域', () => {
    const f = filterTree(buildTree(DOMAINS), 'KEEP')
    expect(f).toHaveLength(1)
    expect(f[0]!.items.map((i) => i.node.id)).toEqual(['bgp.peer.keepalive'])
    expect(filterTree(buildTree(DOMAINS), ' ')).toHaveLength(2)
  })
})

describe('依赖与统计', () => {
  const deps = DOMAINS.flatMap((d) => d.deps)
  it('节点的出边与入边', () => {
    expect(edgesOf(deps, 'interface.ipv4')).toEqual([
      { style: 'cross', kind: 'cross_device', other: 'bgp.peer', dir: 'in', note: '' },
      { style: 'mutex', kind: 'mutex', other: 'interface.l2', dir: 'in', note: '' },
    ])
    expect(edgesOf(deps, 'interface.vrf')[0]).toMatchObject({ style: 'ref', other: 'vrf', dir: 'out' })
  })
  it('依赖规则按 Profile 生效', () => {
    expect(depApplies(deps[2]!, 'p1')).toBe(true)
    expect(depApplies(deps[2]!, 'p2')).toBe(false)
    expect(depApplies(deps[2]!, null)).toBe(true)
    expect(depApplies(deps[0]!, 'p2')).toBe(true)
  })
  it('覆盖率不计已废弃节点，缺失按未填写', () => {
    const nodes = DOMAINS[0]!.nodes
    const m = { 'bgp.af': { p: 'supported' }, 'bgp.instance': { p: 'supported' }, 'bgp.peer': { p: 'unsupported' }, 'bgp.peer.old': { p: 'supported' } } as const
    expect(coverageOf(nodes, m, 'p')).toEqual({ sup: 2, tot: 5, unf: 2, uns: 1, pct: 40 })
    expect(coverageOf([], m, 'p').pct).toBe(0)
  })
  it('可信度只数支持的条目', () => {
    const c = credibilityCounts(
      [
        { node: 'a', state: 'supported', credibility: 'draft' },
        { node: 'b', state: 'supported', credibility: 'reviewed' },
        { node: 'c', state: 'unfilled' },
        { node: 'd', state: 'supported', credibility: 'draft' },
      ],
      new Set(['d']),
    )
    expect(c).toEqual({ verified: 0, reviewed: 1, draft: 1 })
  })
  it('对比结果分组', () => {
    const row = (n: string, kind: CompareRow['kind']): CompareRow => ({
      node: n, domain: 'x', semantic: {}, kind, a: { state: 'supported', default: 1 }, b: { state: 'supported', default: 2 },
    })
    const g = compareGroups([row('a', 'same'), row('b', 'only_a'), row('c', 'only_b'), row('d', 'default'), row('e', 'unfilled'), row('f', 'only_a')], new Set(['f']))
    expect([g.onlyA, g.onlyB, g.defaults, g.unfilled].map((x) => x.map((r) => r.node))).toEqual([['b'], ['c'], ['d'], ['e']])
  })
  it('默认值显示', () => {
    expect(fmtValue(null)).toBe('')
    expect(fmtValue(9000)).toBe('9000')
    expect(fmtValue(false)).toBe('false')
    expect(fmtValue([1, 2])).toBe('[1,2]')
  })
})

describe('布局', () => {
  it('预设分栏，未知功能域放到最短的一栏', () => {
    const cols = assignColumns([
      { domain: 'interface', size: 23 }, { domain: 'vrf', size: 10 }, { domain: 'static-route', size: 8 },
      { domain: 'bgp', size: 33 }, { domain: 'routing-policy', size: 19 }, { domain: 'mpls', size: 3 },
    ])
    expect(cols).toEqual([['interface', 'mpls'], ['vrf', 'static-route', 'routing-policy'], ['bgp']])
    expect(assignColumns([{ domain: 'bgp', size: 1 }])).toEqual([['bgp']])
  })
  it('胶囊按深度缩进，同栏功能域上下排列', () => {
    const l = layoutGroups(buildTree(DOMAINS))
    const inst = l.pos.get('bgp.instance')!, af = l.pos.get('bgp.af')!
    expect(af.x - inst.x).toBe(14)
    expect(af.w).toBe(inst.w - 14)
    expect(l.groups.map((g) => g.domain)).toEqual(['interface', 'bgp'])
    expect(l.pos.get('interface')!.col).toBe(0)
    expect(inst.col).toBe(1)
    expect(l.width).toBeGreaterThan(2 * CW)
  })
  it('边路径：同栏绕右侧，跨栏连接相对的两侧', () => {
    const l = layoutGroups(buildTree(DOMAINS))
    const a = l.pos.get('interface.vrf')!, b = l.pos.get('interface.ipv4')!, c = l.pos.get('bgp.peer')!
    expect(edgePath(a, b, 0).startsWith(`M${a.x + a.w} ${a.y + PH / 2}C`)).toBe(true)
    expect(edgePath(c, b, 0).startsWith(`M${c.x} `)).toBe(true)
    expect(edgePath(b, c, 0).endsWith(`${c.x} ${c.y + PH / 2}`)).toBe(true)
  })
  it('文字截断', () => {
    expect(fitText('abc', 200, 20)).toBe('abc')
    expect(fitText('a'.repeat(50), 100, 20)).toBe('a'.repeat(10) + '…')
  })
})

describe('节点表单', () => {
  const nodes = DOMAINS.flatMap((d) => d.nodes)
  const types = ['object', 'string', 'integer', 'ref', 'enum']
  it('取值范围两端', () => {
    expect(rangeOf('', ' ')).toEqual({ ok: true, value: null })
    expect(rangeOf('1', '4094')).toEqual({ ok: true, value: [1, 4094] })
    expect(rangeOf('-5', '5').value).toEqual([-5, 5])
    expect(rangeOf('9', '1')).toMatchObject({ ok: false, error: 'err.range' })
    expect(rangeOf('1', '')).toMatchObject({ ok: false, error: 'err.rangeBoth' })
    expect(rangeOf('a', '3')).toMatchObject({ ok: false, error: 'err.rangeNum' })
  })
  it('列表输入去重去空', () => {
    expect(splitList(' a | b,a\n\nc ')).toEqual(['a', 'b', 'c'])
  })
  it('节点 → 表单 → 提交体往返不变', () => {
    const n = node('vrf.label_mode', 'vrf', { type: 'enum', choices: ['per-route', 'per-instance'], status: 'reviewed' })
    const f = nodeToForm(n)
    expect(f.choices).toEqual(['per-route', 'per-instance'])
    expect(isDirty(f, n)).toBe(false)
    expect(formToBody(f)).toEqual({
      parent: 'vrf', type: 'enum', key: [], semantic: { 'zh-CN': 'vrf.label_mode', en: 'vrf.label_mode' }, range: null,
      choices: ['per-route', 'per-instance'], ordered: false, ref: null, deprecated: false, replaced_by: null, status: 'reviewed',
    })
    f.semantic['pt-BR'] = '  modo '
    expect(isDirty(f, n)).toBe(true)
    expect(formToBody(f).semantic['pt-BR']).toBe('modo')
  })
  it('ref 只在 ref 类型时提交，replaced_by 只在废弃时提交', () => {
    const f = nodeToForm(node('a', null, { type: 'ref', ref: 'vrf' }))
    expect(formToBody(f).ref).toBe('vrf')
    f.type = 'string'
    expect(formToBody(f).ref).toBeNull()
    f.replaced_by = 'b'
    expect(formToBody(f).replaced_by).toBeNull()
    f.deprecated = true
    expect(formToBody(f).replaced_by).toBe('b')
  })
  it('新建子节点的初始值', () => {
    expect(newForm(nodes[0]!)).toMatchObject({ id: 'bgp.af.', parent: 'bgp.af', status: 'draft' })
    expect(newForm(null).parent).toBe('')
  })
  it('后代集合', () => {
    expect([...descendants(nodes, 'bgp.instance')].sort()).toEqual(['bgp.af', 'bgp.af.network', 'bgp.instance', 'bgp.peer', 'bgp.peer.keepalive', 'bgp.peer.old'])
  })
  it('校验', () => {
    const f = newForm(nodes[2]!)
    expect(validateForm(f, nodes, types, true)).toMatchObject({ id: 'err.id', semantic: 'err.semantic' })
    f.id = 'bgp.af'
    expect(validateForm(f, nodes, types, true).id).toBe('err.idExists')
    f.id = 'bgp.instance.timer'
    f.semantic.en = 'Timer'
    f.type = 'integer'
    f.rangeMin = '5'
    f.rangeMax = '1'
    expect(validateForm(f, nodes, types, true)).toEqual({ range: 'err.range' })
    f.type = 'string' // 不适用的取值范围不再校验
    expect(validateForm(f, nodes, types, true)).toEqual({})
    const e = nodeToForm(nodes[2]!)
    e.parent = 'bgp.peer'
    e.type = 'nope'
    expect(validateForm(e, nodes, types, false)).toEqual({ parent: 'err.parentCycle', type: 'err.type' })
    const d = nodeToForm(nodes[4]!)
    d.deprecated = true
    d.replaced_by = d.id
    expect(validateForm(d, nodes, types, false)).toEqual({ replaced_by: 'err.replacedSelf' })
    d.replaced_by = 'zzz'
    expect(validateForm(d, nodes, types, false)).toEqual({ replaced_by: 'err.refMissing' })
  })
  it('删除前检查分组与后端错误详情', () => {
    const g = usageGroups({ node: 'x', children: [], referenced_by: ['a'], deps: [], profiles: ['p1', 'p2'], manual_entries: [], cards: ['c'], blocking: true })
    expect(g.map((x) => `${x.key}:${x.items.length}`)).toEqual(['referenced_by:1', 'profiles:2', 'cards:1'])
    expect(usageGroups(null)).toEqual([])
    expect(errorDetails(['e1', { a: 1 }])).toEqual(['e1', '{"a":1}'])
    expect(errorDetails(null)).toEqual([])
  })
})

describe('按类型的设置项（M6-9）', () => {
  const nodes = DOMAINS.flatMap((d) => d.nodes)
  const types = ['object', 'string', 'integer', 'ref', 'enum', 'ipv4', 'boolean']

  it('各类型适用的设置项', () => {
    expect(fieldsFor('integer')).toEqual(['range'])
    expect(fieldsFor('enum')).toEqual(['choices'])
    expect(fieldsFor('object')).toEqual(['key', 'ordered'])
    expect(fieldsFor('ref')).toEqual(['ref'])
    for (const t of ['ipv4', 'prefix', 'rd', 'asn', 'interface', 'boolean', 'string', 'text']) expect(fieldsFor(t)).toEqual([])
  })

  it('换类型：提示不再适用的已填内容，提交体清掉它们', () => {
    const f = nodeToForm(nodes[4]!) // integer，range [0, 21845]
    expect(staleFields(f)).toEqual([])
    f.type = 'enum'
    f.choices = ['a']
    expect(staleFields(f)).toEqual(['range'])
    expect(formToBody(f)).toMatchObject({ type: 'enum', range: null, choices: ['a'], key: [], ordered: false, ref: null })
    const o = nodeToForm(node('x', null, { type: 'object', key: ['name'], ordered: true }))
    o.type = 'ipv4'
    expect(staleFields(o)).toEqual(['key', 'ordered'])
    expect(formToBody(o)).toMatchObject({ key: [], ordered: false })
    o.type = 'object'
    expect(formToBody(o)).toMatchObject({ key: ['name'], ordered: true })
  })

  it('enum 至少一个、不能重复；ref 必填且只能指向 object', () => {
    const f = nodeToForm(node('bgp.peer.mode', 'bgp.peer', { semantic: { en: 'm' } }))
    f.type = 'enum'
    expect(validateForm(f, nodes, types, false)).toEqual({ choices: 'err.choicesEmpty' })
    f.choices = ['a', 'a']
    expect(validateForm(f, nodes, types, false)).toEqual({ choices: 'err.choicesDup' })
    f.choices = ['a', 'b']
    expect(validateForm(f, nodes, types, false)).toEqual({})
    f.type = 'ref'
    expect(validateForm(f, nodes, types, false)).toEqual({ ref: 'err.refRequired' })
    f.ref = 'bgp.peer.keepalive'
    expect(validateForm(f, nodes, types, false)).toEqual({ ref: 'err.refNotObject' })
    f.ref = 'bgp.peer'
    expect(validateForm(f, nodes, types, false)).toEqual({})
  })

  it('格式校验', () => {
    expect(formatOk('ipv4', '10.0.0.1')).toBe(true)
    expect(formatOk('ipv4', '10.0.0.256')).toBe(false)
    expect(formatOk('ipv4', '')).toBe(true)
    expect(isMask('255.255.255.0')).toBe(true)
    expect(isMask('255.0.255.0')).toBe(false)
    expect(isPrefix('10.1.0.0/16')).toBe(true)
    expect(isPrefix('10.1.0.0/33')).toBe(false)
    expect(isPrefix('2001:db8::/32')).toBe(true)
    expect(isRd('65000:100')).toBe(true)
    expect(isRd('10.0.0.1:1')).toBe(true)
    expect(isRd('65000')).toBe(false)
    expect(isAsn('65001')).toBe(true)
    expect(isAsn('1.10')).toBe(true)
    expect(isAsn('0')).toBe(false)
    expect(isAsn('4294967296')).toBe(false)
    expect(isCommunity('no-export')).toBe(true)
    expect(isCommunity('65000:70000')).toBe(false)
    expect(formatOk('interface', 'system')).toBe(true)
    expect(formatOk('interface', 'Gi 0/0/1')).toBe(false)
    expect(formatOk('string', 'any thing')).toBe(true)
  })
})
