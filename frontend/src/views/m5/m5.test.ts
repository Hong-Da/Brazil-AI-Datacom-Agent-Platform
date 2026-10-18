import { describe, expect, it } from 'vitest'
import {
  foldRows, groupItems, itemOfNode, markWords, matrixRow, noneffByObject, objectLog, objectOptions, pairLines, pickPoint, timelineX,
  type Item, type ObjSnap, type TextLine,
} from './history'
import { cellText, cliText, columnItems, moveKey, sortRows, tableBody, type Preset, type Row, type Selection } from './exportTable'
import { defaultDiffers, kindFor, quickAnswer, sortDiff, supOf, synParts, type DiffRow, type Feature, type ProfileInfo } from './features'
import { issueGroups, queryParts, stageViews, stmtCls, stmtCounts, takeHandoff, saveHandoff, type GuardResult, type Statement } from './ask'

describe('版本历史', () => {
  it('时间轴：按时间比例，相邻点至少隔开 minGap，首尾落在边界', () => {
    const xs = timelineX([0, 1, 2, 1000], 0, 300, 40)
    expect(xs[0]).toBe(0)
    expect(xs[3]).toBeCloseTo(300)
    expect(xs[1] - xs[0]).toBeGreaterThanOrEqual(10)
    expect(timelineX([5], 10, 30)).toEqual([20])
    expect(timelineX([1, 1, 1], 0, 100)).toEqual([0, 50, 100])
  })
  it('点击设 A / B 的规则', () => {
    expect(pickPoint(5, 2, 4, false)).toEqual([2, 5])
    expect(pickPoint(1, 2, 4, false)).toEqual([1, 4])
    expect(pickPoint(3, 2, 4, true)).toEqual([3, 4])
    expect(pickPoint(4, 2, 4, true)).toEqual([2, 4])
  })
  it('按功能域分组、等值项按对象归并、行归到最长前缀的对象', () => {
    const it1 = { object: 'interface[G0]', domain: 'interface' } as Item
    const it2 = { object: 'acl[1]', domain: 'acl' } as Item
    const it3 = { object: 'interface[G1]', domain: 'interface' } as Item
    expect(groupItems([it1, it2, it3]).map((g) => [g.domain, g.items.length])).toEqual([['interface', 2], ['acl', 1]])
    const ne = noneffByObject([
      { node: 'i[1]/ipv4[a]/plen', schema: 'interface.ipv4.prefix_length', domain: 'interface', object: 'i[1]/ipv4[a]', reason: 'spelling', a: { value: 30, origin: 'explicit', lines: [] }, b: { value: 30, origin: 'explicit', lines: [] } },
    ])
    expect(ne[0].object).toBe('i[1]/ipv4[a]')
    expect(itemOfNode('interface[G0]/mtu', ['interface[G0]', 'interface[G0]/ipv4[x]'])).toBe('interface[G0]')
    expect(itemOfNode('interface[G0]/ipv4[x]/address', ['interface[G0]', 'interface[G0]/ipv4[x]'])).toBe('interface[G0]/ipv4[x]')
    expect(itemOfNode('interface[G01]/mtu', ['interface[G0]'])).toBeNull()
  })
  it('原文差异：删除 + 新增配成并排行，相同行折叠并可展开', () => {
    const L = (op: TextLine['op'], a: number | null, b: number | null, text: string, node: string | null = null): TextLine => ({ op, a, b, text, node, fmt: false })
    const lines: TextLine[] = [...Array.from({ length: 10 }, (_, i) => L('equal', i + 1, i + 1, `l${i}`)), L('del', 11, null, 'mtu 9000', 'if[1]/mtu'), L('add', null, 11, 'mtu 9216', 'if[1]/mtu'), L('add', null, 12, 'x'), L('equal', 12, 13, 'end')]
    const rows = pairLines(lines)
    expect(rows.filter((r) => r.kind === 'ch')).toHaveLength(2)
    expect(rows[10].a?.text).toBe('mtu 9000')
    expect(rows[10].b?.text).toBe('mtu 9216')
    expect(rows[11].a).toBeNull()
    const segs = foldRows(rows, () => false, new Set())
    expect(segs[0]).toMatchObject({ type: 'fold', count: 7 })
    const open = foldRows(rows, () => false, new Set(['0']))
    expect(open.every((s) => s.type === 'row')).toBe(true)
    const [a, b] = markWords('mtu 9000', 'mtu 9216')
    expect(a.filter((p) => p.mark).map((p) => p.s)).toEqual(['9000'])
    expect(b.filter((p) => p.mark).map((p) => p.s)).toEqual(['9216'])
  })
  it('对象历史：相同取值连成一段，变化、新出现、默认值与不存在', () => {
    const S = (seq: number, present: boolean, v?: unknown, origin = 'explicit', changed: string[] = []): ObjSnap => ({ id: seq, seq, collected_at: '', tag: null, present, lines: [], values: v === undefined ? {} : { mtu: { value: v, origin, lines: [] } }, changed })
    const snaps = [S(1, false), S(2, true, 1500, 'default', ['@presence']), S(3, true, 1500, 'default'), S(4, true, 9000, 'explicit', ['mtu'])]
    const row = matrixRow(snaps, 'mtu')
    expect(row.map((c) => [c.kind, c.span, c.cls])).toEqual([['abs', 1, ''], ['val', 2, 'def'], ['val', 1, 'chg']])
    expect(row[0].label).toBe('notYet')
    const log = objectLog(snaps)
    expect(log.map((e) => e.kind)).toEqual(['mod', 'add'])
    expect(log[0].fields[0]).toMatchObject({ field: 'mtu' })
  })
  it('对象选择列表只取显式对象，按 Schema 首段分组', () => {
    const g = objectOptions([
      { id: 'interface[G0]', kind: 'object', schema: 'interface' },
      { id: 'bgp.instance[1]', kind: 'object', schema: 'bgp.instance' },
      { id: 'x', kind: 'attr', schema: 'interface.mtu' },
      { id: 'd', kind: 'object', schema: 'interface', origin: 'derived' },
    ])
    expect(g.map((x) => [x.group, x.items.length])).toEqual([['interface', 1], ['bgp', 1]])
  })
})

describe('表格导出', () => {
  const preset = {
    id: 'ip-address', aliases: ['ip'], object: 'interface', title: {}, description: {}, where: ['has-ip'], filters: [],
    columns: [{ key: 'name', field: 'name', derive: null, schema: null, type: 'key', secret: false, label: { en: 'Interface' }, empty: null }, { key: 'derive:mask', field: null, derive: 'mask', schema: null, type: 'derived', secret: false, label: { en: 'Mask' }, empty: null, off: true }],
  } as unknown as Preset
  it('列清单：模板列在前（off 的不勾选），其余字段与派生列在后', () => {
    const cols = columnItems(preset, [{ path: 'name', type: 'key', secret: false, semantic: {} }, { path: 'mtu', type: 'integer', secret: false, semantic: {} }], ['mask', 'other'])
    expect(cols.map((c) => [c.key, c.on])).toEqual([['name', true], ['derive:mask', false], ['mtu', false], ['derive:other', false]])
    const moved = moveKey(cols, 'mtu', 'name')
    expect(moved.map((c) => c.key)[0]).toBe('mtu')
  })
  it('请求体与 CLI：模板 / 设备 / 筛选 / 默认值', () => {
    const s: Selection = { preset, object: 'interface', columns: columnItems(preset, [], []).map((c) => ({ ...c, on: true })), where: ['has-ip'], adhoc: [{ field: 'mtu', op: '>', value: '1500' }, { field: 'vrf', op: 'exists', value: '' }], devices: ['A'], allDevices: false, defaults: false, canonical: false, style: 'huawei' }
    const b = tableBody(s)
    expect(b).toMatchObject({ preset: 'ip-address', columns: ['name', 'derive:mask'], devices: ['A'], defaults: false, filters: [{ field: 'mtu', op: '>', value: '1500' }, { field: 'vrf', op: 'exists' }] })
    const cli = cliText(s, 'xlsx', 'per-device', 'en')
    expect(cli).toContain('--preset ip-address')
    expect(cli).toContain('--fields name,derive:mask')
    expect(cli).toContain('--no-defaults')
    expect(cli).toContain("--filter 'vrf exists'")
    expect(tableBody({ ...s, preset: null, allDevices: true })).toMatchObject({ object: 'interface', devices: 'all' })
  })
  it('预览排序与格子文字', () => {
    const R = (device: string, key: string, line: number): Row => ({ device, device_id: 1, version_id: 1, profile: '', node: key, key, lines: [line], cells: [] })
    const rows = [R('B', 'x', 1), R('A', 'z', 9), R('A', 'y', 2)]
    expect(sortRows(rows, 'dev', ['A', 'B']).map((r) => r.key)).toEqual(['y', 'z', 'x'])
    expect(sortRows(rows, 'key', ['A', 'B']).map((r) => r.key)).toEqual(['x', 'y', 'z'])
    expect(cellText({ value: ['ipv4', 'vpnv4'], origin: 'derived', nodes: [], lines: [] })).toBe('ipv4, vpnv4')
    expect(cellText({ value: null, origin: 'none', nodes: [], lines: [] })).toBe('')
  })
})

describe('特性能力查询', () => {
  const profiles: ProfileInfo[] = [
    { id: 'hw', title: '', vendor: 'huawei', family: 'huawei-vrp8', platform: '', software: '', inherits: null },
    { id: 'hw2', title: '', vendor: 'huawei', family: 'huawei-vrp8', platform: '', software: '', inherits: 'hw' },
    { id: 'cs', title: '', vendor: 'cisco', family: 'cisco-iosxe', platform: '', software: '', inherits: null },
  ]
  const f: Feature = {
    node: 'bgp.log', domain: 'bgp', type: 'boolean', semantic: { en: 'Log' }, range: null, choices: null, kind: 'differs', score: 80,
    profiles: { hw: { state: 'supported', default: true, syntax: ['log-peer-change'] }, hw2: { state: 'supported', default: true, inherited: true }, cs: { state: 'supported', default: false, syntax: ['bgp log-neighbor-changes'] } },
  }
  it('格子标记、差异判断与默认值不同', () => {
    expect(supOf(f.profiles.hw)).toBe('y')
    expect(supOf(f.profiles.hw2)).toBe('i')
    expect(supOf(undefined)).toBe('u')
    expect(supOf({ state: 'unsupported' })).toBe('n')
    expect(kindFor(f, ['hw', 'hw2'])).toBe('same')
    expect(kindFor(f, ['hw', 'cs'])).toBe('differs')
    expect(kindFor({ ...f, profiles: { hw: f.profiles.hw } }, ['hw', 'cs'])).toBe('gap')
    expect(defaultDiffers(f, ['hw', 'cs'], 'cs')).toBe(true)
    expect(defaultDiffers(f, ['hw', 'cs'], 'hw')).toBe(false)
  })
  it('一句话结论：支持数、默认值、各平台族的写法', () => {
    const a = quickAnswer([f], profiles)!
    expect(a.supported).toEqual(['hw', 'hw2', 'cs'])
    expect(a.defaults).toEqual(['true', 'false'])
    expect(a.syntaxByFamily.map((x) => x.syntax)).toEqual(['log-peer-change', 'bgp log-neighbor-changes'])
    expect(quickAnswer([], profiles)).toBeNull()
  })
  it('命令语法着色与对比排序', () => {
    expect(synParts('mtu <mtu> [ a | b ]').filter((p) => p.c).map((p) => p.s)).toEqual(['<mtu>', '[', '|', ']'])
    const D = (node: string, kind: DiffRow['kind']) => ({ node, kind } as DiffRow)
    expect(sortDiff([D('b', 'unfilled'), D('a', 'only_a'), D('c', 'default')]).map((r) => r.kind)).toEqual(['default', 'only_a', 'unfilled'])
  })
})

describe('AI 查询与护栏', () => {
  it('查询语句着色', () => {
    const p = queryParts('FIND interface WHERE vrf = "RAN" RETURN name')
    expect(p.filter((x) => x.c === 'k').map((x) => x.s)).toEqual(['FIND', 'WHERE', 'RETURN'])
    expect(p.filter((x) => x.c === 's').map((x) => x.s)).toEqual(['"RAN"'])
  })
  it('逐句核对状态与计数', () => {
    const st = [{ status: 'passed' }, { status: 'corrected' }, { status: 'unverifiable' }, { status: 'passed' }] as Statement[]
    expect(stmtCounts(st)).toEqual({ passed: 2, corrected: 1, unverifiable: 1 })
    expect(st.map((s) => stmtCls(s.status))).toEqual(['ok', 'bad', 'na', 'ok'])
  })
  it('护栏阶段与问题分组', () => {
    const g = {
      verdict: 'blocked', lines: [], summary: { lines: 5, bad: 1, warn: 1, ok: 0, skipped: 0 },
      stages: { parse: { status: 'warn', bad: 0, warn: 1 }, graph: { status: 'ok', bad: 0, warn: 0, lines: 4 }, deps: { status: 'bad', bad: 1, warn: 0 }, template: { status: 'skipped', bad: 0, warn: 0 }, conflict: { status: 'ok', bad: 0, warn: 0 } },
      issues: [{ id: 'i1', status: 'warn' }, { id: 'i2', status: 'bad' }],
    } as unknown as GuardResult
    const v = stageViews(g, true)
    expect(v.map((x) => x.cls)).toEqual(['ai', 'warn', 'ok', 'bad', 'none', 'ok'])
    expect(v[4].skipped).toBe(true)
    expect(stageViews(g, false)[0].cls).toBe('none')
    expect(issueGroups(g.issues).map((x) => x.status)).toEqual(['bad', 'warn'])
  })
  it('交给增量变更：存一次、取一次', () => {
    expect(saveHandoff({ device: 3, text: 'sysname X' })).toBe(true)
    expect(takeHandoff()).toEqual({ device: 3, text: 'sysname X' })
    expect(takeHandoff()).toBeNull()
  })
})
