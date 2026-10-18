import { describe, expect, it } from 'vitest'
import {
  canApply, durationSec, parseIso, fmtBytes, fmtDuration, groupByDir, ingestBody, ingestStats, isImportPlan,
  stageIndex, stageStates, validateIngest, type ImportPlan, type IngestForm,
} from './logic'

const form = (o: Partial<IngestForm> = {}): IngestForm => ({
  doc_dir: ' /data/docs ', rules: 'huawei-vrp8-md', domains: ['bgp', 'interface'], version: ' V800R023 ', use_ai: false, ...o,
})

describe('抽取表单', () => {
  it('校验必填项与 AI 状态', () => {
    expect(validateIngest(form(), false)).toEqual([])
    expect(validateIngest(form({ doc_dir: '  ', rules: '', domains: [] }), false)).toEqual(['errDocDir', 'errRules', 'errDomains'])
    expect(validateIngest(form({ use_ai: true }), false)).toEqual(['errAi'])
    expect(validateIngest(form({ use_ai: true }), true)).toEqual([])
  })
  it('请求体去掉空白，功能域按固定顺序', () => {
    expect(ingestBody(form())).toEqual({
      doc_dir: '/data/docs', rules: 'huawei-vrp8-md', domains: ['interface', 'bgp'], version: 'V800R023', use_ai: false,
    })
  })
})

describe('任务阶段', () => {
  it('按进度划分阶段', () => {
    expect([0, 2, 5, 60, 79, 80, 89, 90, 99].map(stageIndex)).toEqual([0, 0, 1, 1, 1, 2, 2, 3, 3])
    expect(stageStates(50, 'running')).toEqual(['done', 'cur', 'todo', 'todo'])
    expect(stageStates(100, 'done')).toEqual(['done', 'done', 'done', 'done'])
  })
  it('不带时区的时间按 UTC 解析', () => {
    expect(parseIso('2026-10-18T01:02:33.352283')).toBe(Date.UTC(2026, 9, 18, 1, 2, 33, 352))
    expect(parseIso('2026-10-18T01:02:33+08:00')).toBe(Date.UTC(2026, 9, 17, 17, 2, 33))
    expect(parseIso(null)).toBeNaN()
  })
  it('耗时', () => {
    expect(durationSec('2026-10-17T10:00:00', '2026-10-17T10:07:12')).toBe(432)
    expect(durationSec(null, '2026-10-17T10:00:00')).toBeNull()
    expect(fmtDuration(432)).toBe('7:12')
    expect(fmtDuration(9)).toBe('9s')
    expect(fmtDuration(null)).toBe('—')
  })
})

describe('结果统计', () => {
  it('汇总 service.ingest 的返回', () => {
    const s = ingestStats({
      files: 10, commands: 120, cards: 100, per_domain: { bgp: 60, vrf: 40 }, patched: 2,
      skipped: { excluded: 5, duplicate: 3, syntax_error: 0 }, errors: ['a', 'b'], rules: 'r', family: 'f',
      merge: { new: 30, updated_draft: 5, changed_reviewed: 2, unchanged: 63 }, review_items: 37, commit: null, ai_cards: 4,
    })
    expect(s).toMatchObject({ cards: 100, commands: 120, unchanged: 63, review: 37, added: 30, updated: 5, changed: 2, skipped: 8, errors: 2, aiCards: 4 })
    expect(s.skippedBy).toEqual([['excluded', 5], ['duplicate', 3]])
    expect(s.perDomain[0]).toEqual(['bgp', 60])
  })
  it('空结果不报错', () => {
    expect(ingestStats(null)).toMatchObject({ cards: 0, review: 0, skipped: 0, errors: 0 })
  })
})

describe('知识库包导入', () => {
  const plan = (o: Partial<ImportPlan> = {}): ImportPlan => ({ kb_version: '0.1.0', added: [], unchanged: [], conflicts: [], issues: [], applied: false, ...o })
  it('有新文件或冲突、无校验错误时才可正式导入', () => {
    expect(canApply(plan({ added: ['schema/x.yaml'] }))).toBe(true)
    expect(canApply(plan({ conflicts: ['a'] }))).toBe(true)
    expect(canApply(plan())).toBe(false)
    expect(canApply(plan({ added: ['a'], issues: [{ level: 'error', code: 'c', message: 'm', file: 'f' }] }))).toBe(false)
    expect(canApply(plan({ added: ['a'], applied: true }))).toBe(false)
    expect(canApply(null)).toBe(false)
  })
  it('识别计划对象、按目录计数、格式化大小', () => {
    expect(isImportPlan(plan())).toBe(true)
    expect(isImportPlan({ detail: 'bad zip' })).toBe(false)
    expect(groupByDir(['schema/a.yaml', 'schema/b.yaml', 'kb.yaml', 'commands/x/y.yaml'])).toEqual([['commands/', 1], ['kb.yaml', 1], ['schema/', 2]])
    expect(fmtBytes(512)).toBe('512 B')
    expect(fmtBytes(2048)).toBe('2.0 KB')
    expect(fmtBytes(5 * 1024 * 1024)).toBe('5.0 MB')
  })
})
