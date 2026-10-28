import { describe, expect, it } from 'vitest'
import { blockOf, lines, safeName, snippet, vendorMark } from './common'
import { msg } from './texts'
import * as chg from './change'
import * as imp from './impact'
import * as topo from './topology'
import * as mig from './migration'
import * as bl from './baseline'

const op = (seq: number, action: chg.Action, object: string, after: [number, string][] = [], risk: chg.Risk = 'low'): chg.Op => ({
  seq, action, text: `cmd ${seq}`, context: [], view: 'system', depth: 0, object, label: object, domain: '', card: null,
  target_nodes: [], current_nodes: [], fallback: false, fallback_reason: null, notes: [], risk, risk_reasons: [],
  after: after.map(([s, kind]) => ({ seq: s, kind, node: '', label: '', note: '' })), lines: { current: [], target: [] },
})

describe('M4 共用', () => {
  it('厂商标记、文件名、文本块', () => {
    expect(vendorMark('huawei-vrp8')).toBe('hw')
    expect(vendorMark('cisco-iosxe-asr920-17.15')).toBe('cs')
    expect(vendorMark(null)).toBe('')
    expect(safeName('PE ASR/01')).toBe('PE_ASR_01')
    const all = lines('interface G1\n mtu 9000\n ip address 1.1.1.1 30\n#\ninterface G2\n')
    expect(blockOf(all, 'interface g1').map((x) => x.no)).toEqual([1, 2, 3])
    expect(blockOf(all, 'interface X')).toEqual([])
    expect(snippet(all, [1, 5], 0)).toEqual([{ no: 1, text: 'interface G1' }, null, { no: 5, text: 'interface G2' }])
  })
  it('后端文案按语言渲染，规则文件文案作为 extra', () => {
    expect(msg('change.action.add', {}, 'en')).toBe('add')
    expect(msg('change.action.add', {}, 'zh-CN')).toBe('新增')
    expect(msg('x.y', { a: 1 }, 'en', { 'x.y': { 'zh-CN': '甲{a}', en: 'A{a}', 'pt-BR': 'P{a}' } })).toBe('A1')
    expect(msg('not.registered')).toBe('not.registered')
  })
})

describe('增量变更', () => {
  const ops = [op(1, 'add', 'vrf.instance[A]'), op(2, 'add', 'vrf.instance[A]/af[ipv4]', [[1, 'contains']]), op(3, 'modify', 'interface[G1]/vrf', [[2, 'reference']], 'high'), op(4, 'delete', 'rp.prefix_list[OLD]', [[3, 'referenced_by']], 'medium')]
  it('依赖链、依赖它的命令、风险排序', () => {
    expect(chg.chainOf(ops, 4)).toEqual([{ seq: 3, level: 1, kind: 'referenced_by' }, { seq: 2, level: 2, kind: 'reference' }, { seq: 1, level: 3, kind: 'contains' }])
    expect(chg.dependents(ops, 2).map((d) => d.op.seq)).toEqual([3])
    expect(chg.riskOps(ops).map((o) => o.seq)).toEqual([3, 4])
    expect(chg.matches(ops[2], 'risk')).toBe(true)
    expect(chg.matches(ops[0], 'delete')).toBe(false)
  })
  it('依赖类型映射到边的颜色', () => {
    expect(chg.edgeOf('prerequisite')).toBe('pre')
    expect(chg.edgeOf('undo_first')).toBe('mutex')
    expect(chg.edgeOf('side_effect_cleanup')).toBe('side')
    expect(chg.edgeOf('referenced_by')).toBe('ref')
  })
  it('回滚命令按对象对应：同一对象优先，否则上下级', () => {
    const rb = [op(1, 'delete', 'vrf.instance[A]'), op(2, 'modify', 'interface[G1]/vrf'), op(3, 'add', 'rp.prefix_list[OLD]')]
    const p = chg.pairRollback(ops, rb)
    expect(p.byRb.get(1)).toEqual([1, 2])
    expect(p.byRb.get(2)).toEqual([3])
    expect(p.byFwd.get(2)).toEqual([1])
    expect(p.byFwd.get(4)).toEqual([3])
  })
  it('脚本行：没有 script_rows 时按缩进推出', () => {
    const plan = { script_plain: 'system-view\ninterface G1\n mtu 9000\nquit\ncommit\nreturn\n' } as chg.Plan
    const rows = chg.rowsOf(plan)
    expect(rows.map((r) => r.depth)).toEqual([0, 0, 1, 0, 0, 0])
    expect(rows[0].kind).toBe('frame')
    expect(chg.viewLines([{ kind: 'enter', depth: 0, text: '', seq: null }, { kind: 'cmd', depth: 1, text: '', seq: 1 }, { kind: 'quit', depth: 0, text: '', seq: null }])).toBe(2)
  })
  it('URL 参数与请求体', () => {
    const s = chg.fromQuery({ device: '12', cv: '12', tv: '19' })
    expect(chg.ready(s)).toBe(true)
    expect(chg.changeBody(s, 'cisco', 'en')).toMatchObject({ current: { device_id: 12, version_id: 12 }, target: { device_id: 12, version_id: 19 }, style: 'cisco' })
    expect(chg.toQuery(s)).toEqual({ device: '12', cv: '12', tv: '19' })
    expect(chg.ready({ ...s, tv: 12 })).toBe(false)
    const p = { ...chg.emptySetup(), device: 1, tmode: 'paste' as const, text: 'sysname A' }
    expect(chg.changeBody(p, 'huawei', 'zh-CN').target).toEqual({ text: 'sysname A' })
    expect(chg.fileName('PE 1', 'rollback', '20261018')).toBe('PE_1_rollback_20261018.txt')
  })
})

describe('影响分析', () => {
  const nodes: imp.ImpactNode[] = [
    { node: 'rp.prefix_list[A]', schema: 'rp.prefix_list', kind: 'object', domain: 'routing-policy', depth: 0, via: null, edge: 'seed', direction: 'seed', business: null },
    { node: 'rp.policy[P]/node[10]/match', schema: 'x', kind: 'attr', domain: 'routing-policy', depth: 1, via: 'rp.prefix_list[A]', edge: 'reference', direction: 'up', business: null },
    { node: 'rp.policy[P]', schema: 'rp.policy', kind: 'object', domain: 'routing-policy', depth: 2, via: 'rp.policy[P]/node[10]/match', edge: 'contains', direction: 'up', business: null },
    { node: 'bgp.instance[1]/bgp.peer[1.1.1.1]', schema: 'bgp.peer', kind: 'object', domain: 'bgp', depth: 3, via: 'rp.policy[P]', edge: 'reference', direction: 'up', business: 'peer' },
  ]
  it('路径、深度、分组、概况', () => {
    expect(imp.pathTo(nodes, 'bgp.instance[1]/bgp.peer[1.1.1.1]')).toEqual(nodes.map((n) => n.node))
    expect(imp.withinDepth(nodes, 2).length).toBe(3)
    expect(imp.listed(nodes, true).map((n) => n.depth)).toEqual([2, 3])
    expect(imp.groupBy(imp.listed(nodes, true), 'type').map((g) => g.key)).toEqual(['peer', 'other'])
    expect(imp.groupBy(imp.listed(nodes, false), 'hop').map((g) => g.key)).toEqual(['1', '2', '3'])
    expect(imp.stripCounts(null, nodes)).toMatchObject({ objects: 2, peer: 1, domains: 2 })
  })
  it('起点候选与常用起点、URL 参数', () => {
    const g = [{ id: 'vrf.instance[RAN]', kind: 'object', schema: 'vrf.instance' }, { id: 'interface[Loopback0]', kind: 'object', schema: 'interface' }, { id: 'raw[1]', kind: 'raw', schema: null }]
    expect(imp.searchNodes(g, 'ran', (x) => x).map((n) => n.id)).toEqual(['vrf.instance[RAN]'])
    expect(imp.presets(g).map((n) => n.id)).toEqual(['vrf.instance[RAN]', 'interface[Loopback0]'])
    expect(imp.fromQuery({ device: '3', node: ['a', 'b[x=1,y=]'], dir: 'down', from: 'change' })).toEqual({ device: 3, version: null, nodes: ['a', 'b[x=1,y=]'], dir: 'down', fromChange: true })
  })
})

describe('拓扑与一致性', () => {
  const end = (device: string, i: string, facts: Record<string, unknown> = {}) => ({ device, interface: i, facts })
  const L = (id: string, type: string, sev: topo.Severity | null, over: string | null = null, issues: string[] = []): topo.Link => ({
    id, type, a: end('A', 'GigabitEthernet0/0/1', { mtu: '9000', vrf: '' }), b: end('B', 'GE0/2/1', { mtu: '1500', vrf: '' }), over, confidence: 'high', basis: { rule: `${type}.x` }, issues, severity: sev, segment: '10.0.0.0/30',
  })
  it('同一对接口上的链路合成一条线，状态取最高级别', () => {
    const g = topo.groupLinks([L('s1', 'subnet', null), L('o1', 'ospf', 'error', 's1', ['f1']), L('b1', 'bgp', 'warning'), L('p1', 'pw', null), L('x1', 'bfd', null)])
    expect(g.map((x) => [x.id, x.kind, x.status, x.links.length])).toEqual([['s1', 'phy', 'bad', 2], ['b1', 'bgp', 'warn', 1], ['p1', 'l2', 'ok', 1], ['x1', 'l2', 'ok', 1]])
    expect(topo.protocols(g[0])).toEqual(['ospf'])
    expect(topo.groupOfLink(g).get('o1')?.id).toBe('s1')
    expect(topo.groupsOf(g, 'A').length).toBe(4)
  })
  it('事实对比与短接口名', () => {
    const rows = topo.factRows(L('s1', 'subnet', null))
    expect(rows.find((r) => r.k === 'mtu')).toEqual({ k: 'mtu', a: '9000', b: '1500', diff: true })
    expect(rows.find((r) => r.k === 'vrf')?.diff).toBe(false)
    // BGP 两端视角互为镜像：交叉一致不算不一致，交叉不一致才算（REQ-055-22）
    const bgp = (fb: Record<string, unknown>): topo.Link => ({ ...L('b1', 'bgp', null), a: end('A', '', { local_address: '1.1.1.1', peer_address: '2.2.2.2', local_as: '1', remote_as: '2', update_source: 'Lo0' }), b: end('B', '', fb) })
    const ok = topo.factRows(bgp({ local_address: '2.2.2.2', peer_address: '1.1.1.1', local_as: '2', remote_as: '1', update_source: 'LoopBack0' }))
    expect(ok.filter((r) => r.diff)).toEqual([])
    const bad = topo.factRows(bgp({ local_address: '2.2.2.2', peer_address: '1.1.1.1', local_as: '2', remote_as: '9' }))
    expect(bad.filter((r) => r.diff).map((r) => r.k).sort()).toEqual(['local_as', 'remote_as'])
    expect(topo.shortIf('GigabitEthernet0/0/1')).toBe('GE0/0/1')
    expect(topo.statusOf('info')).toBe('warn')
    expect(topo.maxSeverity([null, 'info', 'error', 'warning'])).toBe('error')
  })
  it('发现的筛选与 CSV', () => {
    const f = (id: string, severity: topo.Severity, devices: string[]): topo.Finding => ({
      id, rule: 'r', severity, domain: '', link: 'l', link_type: 'subnet', device: devices[0], node: null, lines: [], devices,
      ends: [{ device: devices[0], end: 'G1', node: null, schema: null, value: 1, lines: [3] }], message: { key: 'k', params: {} }, suggestion: { key: 's', params: {} },
    })
    const list = [f('1', 'warning', ['A']), f('2', 'error', ['B'])]
    expect(topo.filterFindings(list, '').map((x) => x.id)).toEqual(['2', '1'])
    expect(topo.filterFindings(list, 'warning').map((x) => x.id)).toEqual(['1'])
    expect(topo.filterFindings(list, '', 'B').map((x) => x.id)).toEqual(['2'])
    const csv = topo.findingsCsv(list, (_x, k) => k)
    expect(csv[0][0]).toBe('severity')
    expect(csv[1].slice(3, 7)).toEqual(['A', 'G1', '1', '3'])
  })
})

describe('割接迁移', () => {
  const item = (source: string, target: string | null, confidence: number, basis = 'logical'): mig.MapItem => ({ source, target, kind: 'physical', source_speed: 1, target_speed: 1, basis, confidence, subinterfaces: [], configured: true })
  it('映射表：改过的行才交给后端，空表示不迁移', () => {
    const rows: mig.MapRow[] = [{ item: item('G1', 'GE1', 0.9), edited: null }, { item: item('G2', 'GE2', 0.3), edited: 'GE7' }, { item: item('G3', 'GE3', 0.3), edited: '' }]
    expect(mig.overrides(rows, { X: '-' })).toEqual({ X: '-', G2: 'GE7', G3: '-' })
    expect(rows.map(mig.rowState)).toEqual(['ok', 'manual', 'skip'])
    expect(mig.rowState({ item: item('G4', 'GE4', 0.3), edited: null })).toBe('low')
  })
  it('CSV 导出与导入（与 CLI 同列）', () => {
    const rows = mig.mapCsvRows([item('G1', 'GE1', 0.9)], [{ source: 'Mgmt0', reason: 'management' }])
    expect(rows[0]).toEqual(['source', 'target', 'kind', 'source_speed', 'target_speed', 'basis', 'confidence', 'subinterfaces', 'configured'])
    expect(rows[2].slice(0, 2)).toEqual(['Mgmt0', ''])
    expect(mig.mapFromCsv('﻿source,target,kind\r\nG1,GE1,x\r\n"G2",,y\r\n')).toEqual({ G1: 'GE1', G2: '-' })
    expect(mig.mapFromCsv('a,b\n1,2')).toBeNull()
    expect(mig.parseCsv('a,"b ""c""",d\n')).toEqual([['a', 'b "c"', 'd']])
  })
  it('告警分组、步骤拆分与风险', () => {
    const it2 = (key: string): mig.Item => ({ kind: '', key, node: null, schema: null, lines: [], params: {} })
    expect(['migrate.warn.lag_renumbered', 'migrate.warn.verify_diff', 'translate.unsupported.raw', 'translate.unsupported.no_render', 'translate.warn.default_differs'].map((k) => mig.warnGroup(it2(k)))).toEqual(['map', 'verify', 'raw', 'unsup', 'default'])
    const st = (no: number, phase: string, key: string): mig.Step => ({ no, phase, device: 'old', key, params: {}, commands: [] })
    const s = mig.splitSteps([st(1, 'precheck', 'migrate.step.precheck'), st(2, 'cutover', 'migrate.step.shutdown_old'), st(3, 'rollback', 'migrate.step.rb_check')])
    expect([s.run.length, s.rollback.length]).toEqual([2, 1])
    expect(mig.stepRisk(s.run[1])).toBe('cut')
    expect(mig.stepsText(s.run, (x) => x.key, (d) => d)).toContain('### 2. [cutover] old  migrate.step.shutdown_old')
  })
})

describe('安全基线', () => {
  const r = {
    matrix: { rules: ['a', 'b'], devices: ['R1', 'R2'], cells: [['pass', 'fail'], ['na', 'fail']] },
    rules: [{ id: 'a', severity: 'error' }, { id: 'b', severity: 'warning' }],
    devices: [
      { device: 'R1', family: 'huawei-vrp8', score: 100, failures: [] },
      { device: 'R2', family: 'cisco-iosxe', score: 40, failures: [
        { rule: 'b', severity: 'warning', remedy: ['ntp server <IP>'] },
        { rule: 'a', severity: 'error', remedy: ['line vty 0 4', ' transport input ssh'] },
        { rule: 'a', severity: 'error', remedy: ['line vty 0 4', ' transport input ssh'] },
      ] },
    ],
  } as unknown as bl.BaselineResult
  it('矩阵、概况、得分档', () => {
    expect(bl.cellOf(r, 'b', 'R1')).toBe('na')
    expect(bl.cellOf(r, 'x', 'R1')).toBe('na')
    expect(bl.stripCounts(r)).toEqual({ affected: 1, bySev: { error: 2, warning: 1, info: 0 } })
    expect([bl.scoreBand(50), bl.scoreBand(90), bl.scoreBand(100)]).toEqual(['lo', 'mid', 'hi'])
  })
  it('不符合项归组、参考命令合并（去重）、矩阵 CSV', () => {
    const d = r.devices[1]
    expect(bl.failuresByRule(d, ['a', 'b']).map((g) => [g.rule, g.items.length])).toEqual([['a', 2], ['b', 1]])
    expect(bl.remedyText(d, (x) => x.toUpperCase()).split('\n')).toEqual(['! b B', 'ntp server <IP>', '! a A', 'line vty 0 4', ' transport input ssh'])
    // Nokia 的注释与华为一样用 #
    expect(bl.remedyText({ ...d, family: 'nokia-sros-md' }, (x) => x).split('\n')[0]).toBe('# b b')
    expect(bl.REMEDY_KEYS.map((k) => k.key)).toEqual(['huawei', 'cisco', 'nokia', 'nokia-sros-md'])
    const csv = bl.matrixCsv(r, (x) => x)
    expect(csv[1]).toEqual(['a', 'error', 'a', 'pass', 'fail'])
    expect(csv[csv.length - 1]).toEqual(['score', '', '', 100, 40])
  })
})
