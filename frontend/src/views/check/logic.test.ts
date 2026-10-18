import { describe, expect, it } from 'vitest'
import {
  codeWindows, countBy, emptyFilter, findingKey, format, matches, nodeChips, orderWithCascade, renderText,
  ruleDesc, ruleSource, ruleTitle, severityCounts, sevOnly, toggleIn, toggleSevOnly,
} from './logic'
import { dispositionName, reportName } from './report'
import type { Finding, Rule } from './types'

const f = (rule: string, node: string, extra: Partial<Finding> = {}): Finding => ({
  rule, severity: 'warning', domain: 'routing-policy', node, nodes: [node], lines: [1],
  message: { key: `check.${rule}.message`, params: { node, key: node } },
  suggestion: { key: `check.${rule}.suggestion`, params: { node } },
  ...extra,
})

const rule = (id: string, extra: Partial<Rule> = {}): Rule => ({
  id, builtin: true, target: null, domain: null, severity: 'warning', enabled: true,
  title: { 'zh-CN': '孤儿对象', en: 'Orphan object', 'pt-BR': 'Objeto órfão' },
  message: { 'zh-CN': '{node} 没有被引用', en: '{node} is not referenced' },
  suggestion: { 'zh-CN': '删除 {node}', en: 'Remove {node}', 'pt-BR': 'Remova {node}' },
  ...extra,
})

describe('文案渲染', () => {
  const rules = new Map([['ref.orphan', rule('ref.orphan')]])
  it('内置检查取 /kb/rules 的模板，pt-BR 缺失时回退英文', () => {
    const x = f('ref.orphan', 'rp.policy[A]')
    expect(renderText(x.message, 'zh-CN', {}, rules)).toBe('rp.policy[A] 没有被引用')
    expect(renderText(x.message, 'pt-BR', {}, rules)).toBe('rp.policy[A] is not referenced')
    expect(renderText(x.suggestion, 'pt-BR', {}, rules)).toBe('Remova rp.policy[A]')
  })
  it('规则文件的文案取结果里的 texts', () => {
    const texts = { 'rules.vrf.x.message': { 'zh-CN': 'VRF {node}', en: 'VRF {node} en', 'pt-BR': 'VRF {node} pt' } }
    expect(renderText({ key: 'rules.vrf.x.message', params: { node: 'v' } }, 'pt-BR', texts, rules)).toBe('VRF v pt')
  })
  it('找不到文案时显示键；缺少的参数原样保留', () => {
    expect(renderText({ key: 'check.nope.message', params: {} }, 'en', {}, rules)).toBe('check.nope.message')
    expect(format('{a} {b}', { a: 1 })).toBe('1 {b}')
  })
  it('规则标题、说明与来源', () => {
    expect(ruleTitle('ref.orphan', 'en', rules)).toBe('Orphan object')
    expect(ruleTitle('x.y', 'en', rules)).toBe('x.y')
    expect(ruleDesc(rule('a'), 'en')).toBe('… is not referenced')
    expect(ruleSource(rule('a'))).toBe('builtin')
    expect(ruleSource(rule('a', { builtin: false, file: 'common.yaml' }))).toBe('common.yaml')
    expect(ruleSource(rule('a', { builtin: false, file: 'common.yaml', source: 'x.yaml' }))).toBe('x.yaml')
  })
})

describe('筛选与计数', () => {
  const list = [
    f('ref.dangling', 'a', { severity: 'error', domain: 'bgp' }),
    f('ref.orphan', 'b'),
    f('ref.orphan', 'c', { ignored: true }),
    f('vrf.x', 'd', { severity: 'info', domain: 'vrf' }),
  ]
  it('已忽略的默认隐藏，计数不含被忽略的', () => {
    expect(list.filter((x) => matches(x, emptyFilter())).map((x) => x.node)).toEqual(['a', 'b', 'd'])
    expect(list.filter((x) => matches(x, { ...emptyFilter(), showIgnored: true })).length).toBe(4)
    expect(severityCounts(list)).toEqual({ error: 1, warning: 1, info: 1 })
    expect(countBy(list, (x) => x.rule)).toEqual({ 'ref.dangling': 1, 'ref.orphan': 1, 'vrf.x': 1 })
  })
  it('按严重度、规则、功能域与搜索词筛选', () => {
    const m = (p: Partial<ReturnType<typeof emptyFilter>>) => list.filter((x) => matches(x, { ...emptyFilter(), ...p })).map((x) => x.node)
    expect(m({ sev: ['error', 'info'] })).toEqual(['a', 'd'])
    expect(m({ rules: ['ref.orphan'] })).toEqual(['b'])
    expect(m({ domains: ['vrf'] })).toEqual(['d'])
    expect(m({ q: 'DANGLING' })).toEqual(['a'])
  })
  it('严重度条：只看某一级，再点恢复全部', () => {
    expect(toggleSevOnly([], 'error')).toEqual(['error'])
    expect(toggleSevOnly(['error'], 'error')).toEqual([])
    expect(toggleSevOnly(['error'], '')).toEqual([])
    expect(sevOnly(['info'])).toBe('info')
    expect(sevOnly(['info', 'error'])).toBe('')
    expect(toggleIn(['a'], 'b', true)).toEqual(['a', 'b'])
    expect(toggleIn(['a', 'b'], 'a', false)).toEqual(['b'])
  })
})

describe('级联分组', () => {
  it('级联孤儿排在父孤儿之后并缩进（后端按行号可能先给出级联）', () => {
    const casc = f('ref.orphan_cascade', 'rp.community_list[CL1]', { nodes: ['rp.community_list[CL1]', 'rp.policy[RM1]'] })
    const deeper = f('ref.orphan_cascade', 'rp.prefix_list[P]', { nodes: ['rp.prefix_list[P]', 'rp.community_list[CL1]'] })
    const parent = f('ref.orphan', 'rp.policy[RM1]')
    const other = f('ref.dangling', 'x', { severity: 'error' })
    const rows = orderWithCascade([other, casc, deeper, parent])
    expect(rows.map((r) => [r.f.node, r.depth, r.cascade])).toEqual([
      ['x', 0, false],
      ['rp.policy[RM1]', 0, false],
      ['rp.community_list[CL1]', 1, true],
      ['rp.prefix_list[P]', 2, true],
    ])
    expect(rows[2].key).toBe(findingKey(casc))
  })
  it('父孤儿被筛掉时级联孤儿平铺', () => {
    const casc = f('ref.orphan_cascade', 'c', { nodes: ['c', 'p'] })
    expect(orderWithCascade([casc]).map((r) => [r.depth, r.cascade])).toEqual([[0, true]])
  })
})

describe('涉及节点与原文窗口', () => {
  it('悬空引用补一个不存在的目标；没有图时按编号判断对象 / 属性', () => {
    const d = f('ref.dangling', 'vrf.instance[A]/af[ipv4]/import_policy', {
      nodes: ['vrf.instance[A]/af[ipv4]', 'vrf.instance[A]/af[ipv4]/import_policy'],
      message: { key: 'check.ref.dangling.message', params: { target_type: 'rp.policy', value: 'UNDEF' } },
    })
    expect(nodeChips(d, new Map())).toEqual([
      { id: 'vrf.instance[A]/af[ipv4]', kind: 'object' },
      { id: 'vrf.instance[A]/af[ipv4]/import_policy', kind: 'attr' },
      { id: 'rp.policy[UNDEF]', kind: 'missing' },
    ])
    expect(nodeChips(f('dep.mutex', 'device'), new Map([['device', 'device']]))[0].kind).toBe('node')
    // 图里的来源：默认值 / 派生值节点带上 origin（REQ-028），显式的不带
    const o = nodeChips(d, new Map(), new Map([['vrf.instance[A]/af[ipv4]', 'explicit'], ['vrf.instance[A]/af[ipv4]/import_policy', 'default']]))
    expect(o.map((c) => c.origin)).toEqual([undefined, 'default', undefined])
  })
  it('相关行带上下文，相邻窗口合并，中间用省略行数隔开', () => {
    const lines = Array.from({ length: 30 }, (_, i) => `l${i + 1}`)
    const rows = codeWindows(lines, [5, 7, 20, 99])
    const nos = rows.map((r) => (r.type === 'gap' ? `gap${r.n}` : r.no))
    expect(nos).toEqual([2, 3, 4, 5, 6, 7, 8, 9, 10, 'gap6', 17, 18, 19, 20, 21, 22, 23])
    expect(rows.filter((r) => r.type === 'line' && r.hl).map((r) => (r.type === 'line' ? r.no : 0))).toEqual([5, 7, 20])
    expect(codeWindows(lines, [])).toEqual([])
  })
})

describe('报告文件名', () => {
  it('从 Content-Disposition 取文件名，没有时按约定生成', () => {
    expect(dispositionName('attachment; filename="check-R1.en.md"', 'x')).toBe('check-R1.en.md')
    expect(dispositionName("attachment; filename*=UTF-8''check-%E8%AE%BE%E5%A4%87.zh-CN.html", 'x')).toBe('check-设备.zh-CN.html')
    expect(dispositionName(null, 'fb')).toBe('fb')
    expect(reportName('check', 'PE 01', 'zh-CN', 'html')).toBe('check-PE_01.zh-CN.html')
    expect(reportName('check', null, 'en', 'md')).toBe('check-config.en.md')
  })
})
