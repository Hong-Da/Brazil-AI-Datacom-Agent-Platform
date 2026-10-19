import { describe, expect, it } from 'vitest'
import {
  askRunId, askRunSkill, caseStatus, dayCols, diffCounts, evoSummary, evolveBlock, f2, genRunId, hlParts, inputSummary,
  issueKey, keptVars, moveItem, orderPair, pct, pctOf, rateTone, sameDef, saveBody, sbsRows, stackSegs, stCls, stScore,
  sumCounts, unknownVars, varWhere, varsIn, vname,
} from './logic'
import type { CaseRow, Definition, DiffLine, EvoCase } from './types'

const DEF: Definition = {
  system: 'Grammar: {syntax}\nReply {{"query": "..."}}',
  prompt: 'Devices:\n{devices}\nQuestion: {question}',
  templates: { retry: 'Rejected: {error}' },
  examples: [],
  tools: ['gquery', 'schema'],
  output: { format: 'json', schema: '{"query": "<q>"}' },
}
const VARS = ['syntax', 'devices', 'question', 'error'].map((name) => ({ name, in: 'prompt', desc: {} }))

describe('校验状态', () => {
  it('颜色映射与未知状态', () => {
    expect(['passed', 'corrected', 'rejected', 'unverifiable', 'error'].map(stCls)).toEqual(['ok', 'fix', 'bad', 'na', 'err'])
    expect(stCls('weird')).toBe('na')
    expect(stCls(null)).toBe('na')
  })
  it('得分', () => {
    expect([stScore('passed'), stScore('unverifiable'), stScore('rejected'), stScore('error')]).toEqual([1, 0.5, 0, 0])
  })
})

describe('比例与格式', () => {
  it('通过率格式化', () => {
    expect(pct(0.756)).toBe('76%')
    expect(pct(null)).toBe('—')
    expect(pct(undefined)).toBe('—')
    expect(pctOf(3, 4)).toBe('75%')
    expect(pctOf(1, 0)).toBe('—')
    expect(f2(0.5)).toBe('0.50')
    expect(f2(null)).toBe('—')
  })
  it('通过率颜色', () => {
    expect(rateTone(0.9)).toBe('')
    expect(rateTone(0.75)).toBe('a')
    expect(rateTone(0.2)).toBe('r')
    expect(rateTone(null)).toBe('')
  })
  it('堆叠条跳过 0 并按比例分宽度', () => {
    const s = stackSegs({ passed: 3, rejected: 1, corrected: 0 })
    expect(s.map((x) => x.k)).toEqual(['passed', 'rejected'])
    expect(s[0].w).toBeCloseTo(75)
    expect(stackSegs({})).toEqual([])
  })
  it('合计', () => {
    expect(sumCounts([{ calls: 2, passed: 1 }, { calls: 3, rejected: 2 }])).toMatchObject({ calls: 5, passed: 1, rejected: 2 })
  })
  it('版本名', () => {
    expect(vname('builtin')).toBeNull()
    expect(vname('3')).toBe('v3')
    expect(vname('draft')).toBe('draft')
  })
})

describe('变量高亮切分', () => {
  it('拼回原文，{{ }} 是字面花括号，未登记的变量 known=false', () => {
    const t = 'A {syntax} {{x}} {foo}!'
    const parts = hlParts(t, ['syntax'])
    expect(parts.map((p) => p.s).join('')).toBe(t)
    const v = parts.filter((p) => p.t === 'var')
    expect(v.map((p) => [p.name, p.known])).toEqual([['syntax', true], ['foo', false]])
  })
  it('用到的变量去重', () => {
    expect(varsIn('{a} {b} {a} {{c}}')).toEqual(['a', 'b'])
  })
  it('未登记的变量与出现位置', () => {
    expect(unknownVars(DEF, VARS)).toEqual([])
    expect(unknownVars({ ...DEF, prompt: '{nope}' }, VARS)).toEqual([['prompt', 'nope']])
    expect(varWhere(DEF, 'error')).toEqual(['templates.retry'])
  })
})

describe('定义草稿', () => {
  it('比较忽略工具顺序与空说明', () => {
    expect(sameDef(DEF, { ...DEF, tools: ['schema', 'gquery'] })).toBe(true)
    expect(sameDef({ ...DEF, examples: [{ input: 'a', output: 'b' }] }, { ...DEF, examples: [{ input: 'a', output: 'b', note: ' ' }] })).toBe(true)
    expect(sameDef(DEF, { ...DEF, prompt: 'x' })).toBe(false)
  })
  it('保存内容去掉空说明', () => {
    const b = saveBody({ ...DEF, examples: [{ input: 'a', output: 'b', note: '' }, { input: 'c', output: 'd', note: ' why ' }] }, 'n')
    expect(b.examples).toEqual([{ input: 'a', output: 'b' }, { input: 'c', output: 'd', note: 'why' }])
    expect(b.note).toBe('n')
  })
  it('示例上移下移', () => {
    expect(moveItem([1, 2, 3], 1, -1)).toEqual([2, 1, 3])
    expect(moveItem([1, 2, 3], 2, 1)).toEqual([1, 2, 3])
  })
})

describe('逐行差异', () => {
  const lines: DiffLine[] = [
    { op: 'same', a: 1, b: 1, text: 'x' },
    { op: 'del', a: 2, b: null, text: 'old1' },
    { op: 'del', a: 3, b: null, text: 'old2' },
    { op: 'add', a: null, b: 2, text: 'new1' },
    { op: 'same', a: 4, b: 3, text: 'y' },
    { op: 'add', a: null, b: 4, text: 'tail' },
  ]
  it('增删计数', () => {
    expect(diffCounts(lines)).toEqual({ add: 2, del: 2 })
    expect(diffCounts(undefined)).toEqual({ add: 0, del: 0 })
  })
  it('并排配对：删除与新增逐行配对，缺的一侧为空', () => {
    const r = sbsRows(lines)
    expect(r).toHaveLength(5)
    expect(r[1]).toEqual({ left: { n: 2, text: 'old1', op: 'del' }, right: { n: 2, text: 'new1', op: 'add' } })
    expect(r[2]).toEqual({ left: { n: 3, text: 'old2', op: 'del' }, right: null })
    expect(r[4]).toEqual({ left: null, right: { n: 4, text: 'tail', op: 'add' } })
  })
  it('对比的两个版本按时间排序', () => {
    expect(orderPair(['3', 'builtin'])).toEqual(['builtin', '3'])
    expect(orderPair(['3', '10'])).toEqual(['3', '10'])
    expect(orderPair(['3', '10'], true)).toEqual(['10', '3'])
    expect(orderPair(['3'])).toBeNull()
  })
})

describe('每日调用柱', () => {
  it('上限取 5 的倍数，每 5 天标日期', () => {
    const daily = Array.from({ length: 7 }, (_, i) => ({ date: `2026-10-${String(i + 1).padStart(2, '0')}`, passed: i, rejected: i === 6 ? 1 : 0 }))
    const { top, cols } = dayCols(daily)
    expect(top).toBe(10)
    expect(cols.map((c) => c.label)).toEqual(['10-01', '', '', '', '', '10-06', '10-07'])
    expect(cols[6].segs.map((s) => s.k)).toEqual(['passed', 'rejected'])
    expect(cols[6].segs[0].h).toBeCloseTo(60)
    expect(dayCols([{ date: '2026-10-01' }]).top).toBe(5)
  })
})

describe('进化', () => {
  const side = (status: 'passed' | 'rejected' | 'unverifiable', score: number) => ({ status, score, items: [], reply: '' })
  const cases: EvoCase[] = [
    { case_id: 1, reason: 'rejected', old: side('rejected', 0), new: side('passed', 1), delta: 'better' },
    { case_id: 2, reason: 'down', old: side('unverifiable', 0.5), new: side('unverifiable', 0.5), delta: 'same' },
  ]
  it('评分汇总', () => {
    expect(evoSummary(cases)).toEqual({ old: 0.25, new: 0.75, better: 1, worse: 0, same: 1 })
    expect(evoSummary([])).toEqual({ old: 0, new: 0, better: 0, worse: 0, same: 0 })
  })
  it('候选保留变量', () => {
    expect(keptVars(DEF, { ...DEF, templates: { retry: 'again' } })).toEqual([['syntax', 'devices', 'question'], ['error']])
  })
  it('不能进化的原因', () => {
    const base = { configured: true, sid: 'ask-query', enabled: true, regression: 2, pending: null, running: false }
    expect(evolveBlock(base)).toBe('')
    expect(evolveBlock({ ...base, configured: false })).toBe('evo.whyNoAi')
    expect(evolveBlock({ ...base, sid: 'skill-evolve' })).toBe('evo.whySelf')
    expect(evolveBlock({ ...base, regression: 0 })).toBe('evo.whyNoCases')
    expect(evolveBlock({ ...base, pending: { id: 3 } })).toBe('evo.whyPending')
  })
})

describe('调用记录与反馈', () => {
  it('输入摘要', () => {
    expect(inputSummary({ question: 'MTU?', devices: [] })).toBe('MTU?')
    expect(inputSummary({ n: 1 })).toBe('{"n":1}')
    expect(inputSummary('x'.repeat(200), 10)).toBe(`${'x'.repeat(10)}…`)
    expect(inputSummary(null)).toBe('')
  })
  it('案例最近结论', () => {
    expect(caseStatus({ detail: { summary: { status: 'rejected' } } } as unknown as CaseRow)).toBe('rejected')
    expect(caseStatus({ detail: null } as unknown as CaseRow)).toBe('unverifiable')
  })
  it('AI 查询的反馈记在回答那一条，没有回答时用最后一条', () => {
    const runs = [
      { step: 'query', skill: 'ask-query', version: 'builtin', run_id: 5, status: 'rejected' },
      { step: 'query', skill: 'ask-query', version: 'builtin', run_id: 6, status: 'passed' },
      { step: 'answer', skill: 'ask-answer', version: 'builtin', run_id: 7, status: 'passed' },
    ]
    expect(askRunId({ skill_runs: runs })).toBe(7)
    expect(askRunSkill({ skill_runs: runs })).toBe('ask-answer')
    expect(askRunId({ skill_runs: runs.slice(0, 2) })).toBe(6)
    expect(askRunId({})).toBeNull()
  })
  it('AI 生成的反馈记在最终轮', () => {
    expect(genRunId({ rounds: [{ round: 1, skill_run: 3 }, { round: 2, skill_run: 4 }], final: { round: 2 } })).toBe(4)
    expect(genRunId({ skill_runs: [{ step: 'generate.1', skill: 'config-generate', version: '1', run_id: 9, status: 'passed' }], rounds: [], final: { round: 1 } })).toBe(9)
    expect(genRunId(null)).toBeNull()
  })
  it('问题文案键', () => {
    expect(issueKey('skills.issue.unknown_var')).toBe('issue.unknown_var')
    expect(issueKey('skills.warn.var_dropped')).toBe('warn.var_dropped')
  })
})
