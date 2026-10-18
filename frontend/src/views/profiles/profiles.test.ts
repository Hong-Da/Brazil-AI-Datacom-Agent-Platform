import { describe, expect, it } from 'vitest'
import { toCsv } from './csv'
import { credPercents, formatDefault, parseDefault, shortId, treeOrder, vendorBadge } from './format'
import { entryBody, entryOrigin, filterEntries, formDirty, formFromEntry, type EntryFilter } from './entries'
import { compareCsv, compareSummary, filterCompare, warnOf } from './compare'
import { buildCoverage, coverageCsv, coverageSummary, domainStats, filterCoverage, groupByDomain, type CovFilter } from './coverage'
import type { CompareResult, CoverageResult, Entry, ProfileDetail } from './types'

const E = (node: string, extra: Partial<Entry> = {}): Entry => ({
  node, domain: node.split('.')[0], type: 'string', semantic: { 'zh-CN': node }, deprecated: false, state: 'supported',
  default: null, show_rule: 'hide_when_default', cards: [], source: '', verified: 'doc', manual: false,
  origin: 'p1', inherited: false, credibility: 'draft', ...extra,
})

describe('格式化', () => {
  it('默认值显示与解析', () => {
    expect(formatDefault(null)).toBe('')
    expect(formatDefault(false)).toBe('false')
    expect(formatDefault(1500)).toBe('1500')
    expect(parseDefault('')).toBeNull()
    expect(parseDefault(' true ')).toBe(true)
    expect(parseDefault('1500')).toBe(1500)
    expect(parseDefault('per-instance')).toBe('per-instance')
    expect(parseDefault('100', 'x')).toBe('100')
  })
  it('厂商徽标、简称与可信度百分比', () => {
    expect(vendorBadge('huawei')).toEqual({ cls: 'hw', text: 'HW' })
    expect(vendorBadge('juniper').text).toBe('JU')
    expect(shortId('cisco-iosxe-asr920-17.15')).toBe('iosxe-asr920-17.15')
    expect(credPercents({ credibility: { draft: 5, reviewed: 3, verified: 2 }, entries: 10, unfilled: 10 })).toEqual({ verified: 10, reviewed: 15, draft: 25 })
  })
  it('按继承树排序', () => {
    const l = [{ id: 'cs', inherits: null }, { id: 'hw23', inherits: 'hw25' }, { id: 'hw25', inherits: null }, { id: 'x', inherits: 'gone' }]
    expect(treeOrder(l).map((p) => p.id)).toEqual(['cs', 'hw25', 'hw23', 'x'])
  })
  it('CSV 转义并带 BOM', () => {
    expect(toCsv([['a', 'b,c'], ['x"y', null]])).toBe('﻿a,"b,c"\r\n"x""y",\r\n')
  })
})

describe('Profile 条目', () => {
  const parent = new Map([['bgp.peer', E('bgp.peer')]])
  const list = [
    E('bgp.peer'),
    E('bgp.peer.hold', { credibility: 'reviewed' }),
    E('interface.mtu', { inherited: true, origin: 'p0' }),
    E('interface.old', { deprecated: true }),
    E('vrf.rd', { state: 'unfilled' }),
  ]
  const f: EntryFilter = { q: '', domain: '', origin: '', cred: '', showDeprecated: false }
  it('来源分类', () => {
    expect(entryOrigin(list[0], parent)).toBe('override')
    expect(entryOrigin(list[1], parent)).toBe('own')
    expect(entryOrigin(list[2], parent)).toBe('inherited')
    expect(entryOrigin(list[4], parent)).toBe('unfilled')
  })
  it('筛选：搜索、功能域、来源、可信度、已废弃', () => {
    expect(filterEntries(list, f).map((e) => e.node)).toEqual(['bgp.peer', 'bgp.peer.hold', 'interface.mtu', 'vrf.rd'])
    expect(filterEntries(list, { ...f, q: 'HOLD' }).map((e) => e.node)).toEqual(['bgp.peer.hold'])
    expect(filterEntries(list, { ...f, domain: 'interface', showDeprecated: true }).length).toBe(2)
    expect(filterEntries(list, { ...f, origin: 'own' }, parent).length).toBe(2)
    expect(filterEntries(list, { ...f, origin: 'inherited' }).map((e) => e.node)).toEqual(['interface.mtu'])
    expect(filterEntries(list, { ...f, origin: 'unfilled' }).map((e) => e.node)).toEqual(['vrf.rd'])
    expect(filterEntries(list, { ...f, cred: 'reviewed' }).map((e) => e.node)).toEqual(['bgp.peer.hold'])
  })
  it('编辑表单与请求体', () => {
    const form = formFromEntry(E('interface.mtu', { default: 1500, source: 'doc p.1' }))
    expect(form).toEqual({ supported: true, default: '1500', show_rule: 'hide_when_default', source: 'doc p.1', verified: 'doc' })
    expect(formFromEntry(undefined).supported).toBe(true)
    expect(entryBody({ ...form, default: '9000' }, (t) => parseDefault(t, 1500))).toEqual({
      supported: true, default: 9000, show_rule: 'hide_when_default', source: 'doc p.1', verified: 'doc',
    })
    expect(entryBody({ ...form, supported: false }, parseDefault).default).toBeNull()
    expect(formDirty(form, { ...form })).toBe(false)
    expect(formDirty(form, { ...form, show_rule: 'always' })).toBe(true)
  })
})

describe('Profile 对比', () => {
  const c: CompareResult = {
    a: 'A', b: 'B',
    counts: { same: 1, only_a: 1, only_b: 0, default: 1, unfilled: 1 },
    rows: [
      { node: 'x.same', domain: 'x', semantic: {}, a: { state: 'supported', default: null }, b: { state: 'supported', default: null }, kind: 'same' },
      { node: 'x.only', domain: 'x', semantic: {}, a: { state: 'supported', default: null }, b: { state: 'unsupported', default: null }, kind: 'only_a' },
      { node: 'x.def', domain: 'x', semantic: {}, a: { state: 'supported', default: 60 }, b: { state: 'supported', default: 30 }, kind: 'default' },
      { node: 'y.gap', domain: 'y', semantic: {}, a: { state: 'supported', default: null }, b: { state: 'unfilled', default: null }, kind: 'unfilled' },
    ],
  }
  it('告警分类、筛选与汇总', () => {
    expect(warnOf('only_b')).toBe('unsupported')
    expect(warnOf('same')).toBe('none')
    expect(filterCompare(c.rows, true).length).toBe(3)
    expect(filterCompare(c.rows, false, 'def').map((r) => r.node)).toEqual(['x.def'])
    expect(compareSummary(c)).toEqual({ total: 4, support: 1, default: 1, unfilled: 1, same: 1 })
  })
  it('差异表 CSV', () => {
    const lines = compareCsv(c, filterCompare(c.rows, true)).replace('﻿', '').trim().split('\r\n')
    expect(lines[0]).toBe('node,domain,A state,A default,B state,B default,kind,warning')
    expect(lines[2]).toBe('x.def,x,supported,60,supported,30,default,default')
    expect(lines.length).toBe(4)
  })
})

describe('覆盖矩阵', () => {
  const cov: CoverageResult = {
    profiles: ['cs', 'hw1', 'hw2'],
    totals: {},
    matrix: {
      'bgp.peer': { cs: 'supported', hw1: 'supported', hw2: 'supported' },
      'bgp.peer.hold': { cs: 'supported', hw1: 'supported', hw2: 'supported' },
      'bgp.log': { cs: 'supported', hw1: 'unfilled', hw2: 'unfilled' },
      'interface.l2': { cs: 'unsupported', hw1: 'supported', hw2: 'unsupported' },
      'interface.old': { cs: 'unfilled', hw1: 'supported', hw2: 'supported' },
    },
  }
  const detail = (id: string, entries: Entry[]): ProfileDetail => ({
    profile: { id, title: id, vendor: '', family: '', platform: '', software: '', inherits: null, match: {}, lineage: [id] },
    show_rules: [], entries,
  })
  const details = {
    cs: detail('cs', [E('bgp.peer', { credibility: 'verified' }), E('bgp.peer.hold', { default: 180, credibility: 'verified' }), E('bgp.log', { default: false }), E('interface.l2', { state: 'unsupported' }), E('interface.old', { state: 'unfilled', deprecated: true })]),
    hw1: detail('hw1', [E('bgp.peer', { credibility: 'verified' }), E('bgp.peer.hold', { default: 90, credibility: 'reviewed' }), E('interface.l2'), E('interface.old', { deprecated: true })]),
    hw2: undefined,
  }
  const vendors = { cs: 'cisco', hw1: 'huawei', hw2: 'huawei' }
  const rows = buildCoverage(cov, details, vendors)
  const by = (n: string) => rows.find((r) => r.node === n)!
  const f: CovFilter = { q: '', domain: '', cred: '', gapsOnly: false, diffOnly: false, showDeprecated: false }

  it('组装格子、缺口与厂商差异', () => {
    expect(rows.map((r) => r.node)).toEqual(['bgp.log', 'bgp.peer', 'bgp.peer.hold', 'interface.l2', 'interface.old'])
    expect(by('bgp.peer').cells.cs).toMatchObject({ state: 'supported', cred: 'verified' })
    expect(by('bgp.peer').cells.hw2).toEqual({ state: 'supported' })
    expect(by('bgp.log').gap).toBe(true)
    expect(by('bgp.log').supportDiff).toBe(false)
    expect(by('interface.l2').supportDiff).toBe(true)
    expect(by('bgp.peer.hold').defaultDiff).toEqual([{ vendor: 'cisco', value: '180' }, { vendor: 'huawei', value: '90' }])
    expect(by('interface.old').deprecated).toBe(true)
  })
  it('筛选', () => {
    expect(filterCoverage(rows, f).length).toBe(4)
    expect(filterCoverage(rows, { ...f, showDeprecated: true }).length).toBe(5)
    expect(filterCoverage(rows, { ...f, gapsOnly: true }).map((r) => r.node)).toEqual(['bgp.log'])
    expect(filterCoverage(rows, { ...f, diffOnly: true }).map((r) => r.node)).toEqual(['bgp.peer.hold', 'interface.l2'])
    expect(filterCoverage(rows, { ...f, cred: 'verified' }).map((r) => r.node)).toEqual(['bgp.peer'])
    expect(filterCoverage(rows, { ...f, cred: 'reviewed' }).map((r) => r.node)).toEqual(['bgp.peer.hold'])
    expect(filterCoverage(rows, { ...f, q: 'L2', domain: 'interface' }).length).toBe(1)
  })
  it('分组、功能域覆盖率与汇总', () => {
    expect(groupByDomain(filterCoverage(rows, f)).map((g) => [g.domain, g.rows.length])).toEqual([['bgp', 3], ['interface', 1]])
    expect(domainStats(rows, 'bgp', 'hw1')).toEqual({ pct: 67, gaps: 1 })
    expect(coverageSummary(rows)).toEqual({ nodes: 4, domains: 2, gaps: 1, diffs: 2, draft: 2 })
  })
  it('CSV', () => {
    const lines = coverageCsv(filterCoverage(rows, { ...f, gapsOnly: true }), cov.profiles).replace('﻿', '').trim().split('\r\n')
    expect(lines[0]).toBe('node,domain,type,deprecated,cs,hw1,hw2,support_diff,default_diff')
    expect(lines[1]).toBe('bgp.log,bgp,string,false,supported draft,unfilled,unfilled,false,')
  })
})
