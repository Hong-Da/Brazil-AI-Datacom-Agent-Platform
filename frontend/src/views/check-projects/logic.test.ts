import { describe, expect, it } from 'vitest'
import {
  aiFresh, aiStats, categoriesFor, charSegments, countByCat, countBySev, filterIssues, filterProjects, foldEqual, gutterMarks,
  issuesByLine, Latest, mergeIssues, moveMarks, orderPicks, projectStats, reorderColumns, reportLang, revFrom, revMoves,
  splitLines, squiggles, takeAiSnapshot, togglePick, unifiedRows, wirePath,
} from './logic'
import type { CheckResult, DiffRow, Issue, Project, Revision } from './types'

const iss = (id: string, line: number, severity: Issue['severity'], category: Issue['category'], source: Issue['source'] = 'code', extra: Partial<Issue> = {}): Issue => ({
  id, line, lines: [line], severity, category, code: category, source, text: `${id} text`, message: { key: '', params: {} }, ...extra,
})

const ISSUES = [
  iss('i1', 14, 'error', 'view'),
  iss('i2', 3, 'info', 'override'),
  iss('i3', 3, 'error', 'order'),
  iss('i4', 13, 'warning', 'undo'),
  iss('a1', 5, 'warning', 'ai', 'ai', { status: 'unverifiable', rule: 'naming' }),
  iss('a2', 3, 'info', 'ai', 'ai', { status: 'passed', rule: 'naming' }),
]

function result(issues: Issue[], extra: Partial<CheckResult> = {}): CheckResult {
  return {
    kind: 'change', baseline: null, line_kinds: [], issues,
    order: { enabled: true, applicable: true, violations: 0 },
    result: {}, ai: { enabled: false },
    summary: { errors: 0, warnings: 0, infos: 0, by_category: {}, lines: 0, commands: 0, unknown: 0, ok: true },
    ms: 1, script: { id: 1, saved: false, kind: 'change' }, ...extra,
  }
}

describe('问题按行分组与行号槽标记', () => {
  it('每行按级别排序', () => {
    const m = issuesByLine(ISSUES)
    expect(m.get(3)!.map((x) => x.id)).toEqual(['i3', 'i2', 'a2'])
    expect([...m.keys()]).toEqual([3, 5, 13, 14])
  })
  it('槽标记取最高级别；全部来自 AI 时空心', () => {
    const g = gutterMarks(ISSUES)
    expect(g.get(3)).toMatchObject({ sev: 'error', hollow: false })
    expect(g.get(5)).toMatchObject({ sev: 'warning', hollow: true })
    expect(g.get(3)!.title.split('\n')).toHaveLength(3)
    expect(squiggles(ISSUES)).toContainEqual({ line: 14, sev: 'error' })
  })
  it('计数与筛选', () => {
    expect(countBySev(ISSUES)).toEqual({ error: 2, warning: 2, info: 2 })
    expect(countByCat(ISSUES).ai).toBe(2)
    expect(filterIssues(ISSUES, new Set(['error']), new Set()).map((x) => x.id)).toEqual(['i1', 'i3'])
    expect(filterIssues(ISSUES, new Set(), new Set(['undo', 'view'])).map((x) => x.id)).toEqual(['i1', 'i4'])
    expect(filterIssues(ISSUES, new Set(['warning']), new Set(['undo'])).map((x) => x.id)).toEqual(['i4'])
  })
  it('类别按钮：完整配置不列出只属于变更脚本的类别（出现了的除外）', () => {
    expect(categoriesFor('full', false, {})).toEqual(['parse', 'view', 'rule'])
    expect(categoriesFor('full', true, { undo: 1 })).toEqual(['parse', 'view', 'undo', 'rule', 'ai'])
    expect(categoriesFor('change', false, {})).not.toContain('ai')
  })
})

describe('AI 一起校验的结果合并', () => {
  const code = ISSUES.filter((x) => x.source === 'code')
  const ai = ISSUES.filter((x) => x.source === 'ai')
  const withAi = result(ISSUES, { ai: { enabled: true, accepted: 2, rejected: [{ rule: 'x', line: 2, reason: 'line_invalid' }] } })
  it('快照只对当时的内容与类型有效', () => {
    const snap = takeAiSnapshot(withAi, 'abc')!
    expect(snap.issues).toHaveLength(2)
    expect(aiFresh(snap, 'abc', 'change')).toBe(true)
    expect(aiFresh(snap, 'abcd', 'change')).toBe(false)
    expect(takeAiSnapshot(result(code), 'abc')).toBeNull()
  })
  it('本次没调 AI 时沿用内容没变的快照；AI 关闭时不显示', () => {
    const snap = takeAiSnapshot(withAi, 'abc')
    const plain = result(code)
    expect(mergeIssues(plain, snap, 'abc', 'change', true)).toHaveLength(6)
    expect(mergeIssues(plain, snap, 'changed', 'change', true)).toHaveLength(4)
    expect(mergeIssues(withAi, snap, 'abc', 'change', false)).toHaveLength(4)
    expect(mergeIssues(null, snap, 'abc', 'change', true)).toEqual([])
  })
  it('统计：提出 = 通过的 + 被拦截的', () => {
    expect(aiStats(withAi.ai, [...code, ...ai])).toEqual({ proposed: 3, shown: 2, passed: 1, unverifiable: 1, rejected: 1 })
  })
})

describe('顺序与重排', () => {
  const moves = [
    { line: 4, new_line: 13, text: ' ip binding vpn-instance NEWVPN', reasons: [] },
    { line: 3, new_line: 14, text: ' ip address 10.3.0.1 255.255.255.252', reasons: [] },
  ]
  it('移动槽只在顺序核查开启且有重排建议时出现', () => {
    const r = result([], { order: { enabled: true, applicable: true, violations: 2, reorder: { script: '', moves, mapping: [], changed: true, warnings: [] } } })
    expect([...moveMarks(r).entries()]).toEqual([[4, 13], [3, 14]])
    expect(moveMarks({ ...r, order: { ...r.order, enabled: false } }).size).toBe(0)
    expect(moveMarks(null).size).toBe(0)
  })
  it('重排前后两栏标出另一侧的行号', () => {
    const orig = Array.from({ length: 15 }, (_, i) => `l${i + 1}`).join('\n') + '\n'
    const after = Array.from({ length: 19 }, (_, i) => `n${i + 1}`).join('\n') + '\n'
    const c = reorderColumns(orig, after, moves)
    expect(c.before).toHaveLength(15)
    expect(c.after).toHaveLength(19)
    expect(c.before[3]).toMatchObject({ no: 4, moveIdx: 0, tag: '→ 13' })
    expect(c.after[13]).toMatchObject({ no: 14, moveIdx: 1, tag: '← 3' })
    expect(c.before[0].moveIdx).toBeNull()
  })
  it('连线坐标', () => {
    const w = wirePath(2, 5, 72, 24, 40)
    expect(w.y1).toBe(76)
    expect(w.y2).toBe(148)
    expect(w.d.startsWith('M0 76 C')).toBe(true)
  })
  it('splitLines 与编辑器行号一致', () => {
    expect(splitLines('a\nb\n')).toEqual(['a', 'b'])
    expect(splitLines('a\r\nb')).toEqual(['a', 'b'])
    expect(splitLines('')).toEqual([])
  })
})

describe('文本差异', () => {
  const rows: DiffRow[] = [
    { t: 'equal', a: 1, b: 1, at: 'system-view', bt: 'system-view' },
    { t: 'change', a: 2, b: 2, at: ' description A', bt: ' description AB', sa: [], sb: [[14, 15]] },
    { t: 'move_from', a: 3, b: null, at: ' ip address 1.1.1.1 32', bt: null, to: 5 },
    { t: 'del', a: 4, b: null, at: 'undo x', bt: null },
    { t: 'add', a: null, b: 3, at: null, bt: 'quit' },
    { t: 'move_to', a: null, b: 5, at: null, bt: ' ip address 1.1.1.1 32', from: 3 },
  ]
  it('并排行 → 上下视图：修改拆成两行，移走的行留虚线提示，移入的行标出来源', () => {
    const u = unifiedRows(rows)
    expect(u.map((r) => r.k)).toEqual(['equal', 'mod-del', 'mod-add', 'move-ghost', 'del', 'add', 'move'])
    expect(u[2]).toMatchObject({ b: 2, spans: [[14, 15]] })
    expect(u[3]).toMatchObject({ a: 3, to: 5, text: 'ip address 1.1.1.1 32' })
    expect(u[6]).toMatchObject({ a: 3, b: 5, from: 3 })
  })
  it('行内字符片段', () => {
    expect(charSegments(' description AB', [[14, 15]])).toEqual([{ t: ' description A', hit: false }, { t: 'B', hit: true }])
    expect(charSegments('abc', undefined)).toEqual([{ t: 'abc', hit: false }])
    expect(charSegments('abcdef', [[4, 6], [0, 1]])).toEqual([{ t: 'a', hit: true }, { t: 'bcd', hit: false }, { t: 'ef', hit: true }])
  })
  it('折叠相同的行，保留上下文', () => {
    const eq = (n: number): DiffRow => ({ t: 'equal', a: n, b: n, at: 'x', bt: 'x' })
    const list: DiffRow[] = [...Array.from({ length: 10 }, (_, i) => eq(i + 1)), { t: 'add', a: null, b: 11, at: null, bt: 'y' }, ...Array.from({ length: 10 }, (_, i) => eq(i + 12))]
    const f = foldEqual(list, 3)
    expect(f[0]).toEqual({ fold: 7 })
    expect(f.length).toBe(1 + 3 + 1 + 3 + 1)
    expect(f[f.length - 1]).toEqual({ fold: 7 })
    expect(foldEqual(list.slice(8, 13), 3)).toHaveLength(5)
  })
  it('报告语言：巴西葡萄牙语用英文', () => {
    expect(reportLang('zh-CN')).toBe('zh-CN')
    expect(reportLang('pt-BR')).toBe('en')
    expect(reportLang('en')).toBe('en')
  })
})

describe('修订', () => {
  const rev = (id: number, seq: number, source: Revision['source'], note: Revision['note'] = null): Revision => ({ id, script_id: 1, seq, source, note, summary: null, author: 'u', lines: 1, created_at: '' })
  const revs = [rev(4, 3, 'restore', { from_seq: 1, from_id: 1 }), rev(3, 2, 'reorder', { moves: [{ line: 4, new_line: 13, text: '', reasons: [] }], before_seq: 1 }), rev(1, 1, 'create')]
  it('最多选两条，旧的作 A', () => {
    expect(togglePick([], 1)).toEqual([1])
    expect(togglePick([1, 3], 4)).toEqual([3, 4])
    expect(togglePick([1, 3], 1)).toEqual([3])
    expect(orderPicks([4, 1], revs)!.map((r) => r.seq)).toEqual([1, 3])
    expect(orderPicks([4], revs)).toBeNull()
  })
  it('来源说明', () => {
    expect(revMoves(revs[1])).toBe(1)
    expect(revFrom(revs[0])).toBe(1)
    expect(revFrom(revs[1])).toBe(1)
    expect(revFrom(revs[2])).toBeNull()
  })
})

describe('项目列表', () => {
  const p = (id: number, name: string, owner: string | null, vendor: string, errors: number, version: number | null): Project => ({
    id, name, description: '', device: { id, name: `DEV-${id}`, vendor, platform: '', profile: '' }, device_id: id, version_id: version, profile: null,
    default_kind: 'change', order_check: true, ai_check: false, ai_rules: [], owner: owner ? { id: 1, username: owner } : null, scripts: 2,
    last_check: { errors, warnings: 0, checked: 1, at: null }, created_at: '', updated_at: '',
  })
  const list = [p(1, 'OAM 开通', 'liwei', 'huawei', 1, null), p(2, 'BGP', 'admin', 'cisco', 0, 5), p(3, 'ACL', 'liwei', 'huawei', 0, null)]
  it('筛选：我的、平台、关键字（名称或设备）', () => {
    expect(filterProjects(list, { scope: 'mine', q: '', vendor: '', me: 'liwei' }).map((x) => x.id)).toEqual([1, 3])
    expect(filterProjects(list, { scope: 'all', q: '', vendor: 'cisco', me: null }).map((x) => x.id)).toEqual([2])
    expect(filterProjects(list, { scope: 'all', q: 'dev-3', vendor: '', me: null }).map((x) => x.id)).toEqual([3])
  })
  it('概况', () => {
    expect(projectStats(list, 'liwei')).toEqual({ total: 3, mine: 2, withErrors: 1, scripts: 6, latest: 2 })
  })
  it('只采用最新一次请求的结果', () => {
    const l = new Latest()
    const a = l.next()
    const b = l.next()
    expect(l.isLatest(a)).toBe(false)
    expect(l.isLatest(b)).toBe(true)
  })
})
