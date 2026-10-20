import { describe, expect, it } from 'vitest'
import { aiLineSet, cutoverParams, docLang, flowSteps, gapRows, scopes, sectionState, templateReady } from './logic'

describe('ai-change logic', () => {
  it('scopes match the backend scope keys', () => {
    expect(scopes.intent(3)).toBe('change:3')
    expect(scopes.cutover(3, 'p')).toBe('cutover:3:p')
    expect(scopes.translate(3, 'p')).toBe('translate:3:p')
    expect(scopes.naming(3, 'p')).toBe('naming:3:p')
    expect(scopes.template([5, 2])).toBe('template:2,5')
  })

  it('flow marks the current step', () => {
    expect(flowSteps('idle', 0).filter((s) => s.cur).map((s) => s.k)).toEqual(['nl'])
    expect(flowSteps('done', 0).filter((s) => s.cur).map((s) => s.k)).toEqual(['edit'])
    expect(flowSteps('done', 2).filter((s) => s.cur).map((s) => s.k)).toEqual(['script', 'impact', 'sim'])
    expect(flowSteps('done', 0)[1].kind).toBe('ai')
  })

  it('cutover params come from the migration request', () => {
    expect(cutoverParams(null)).toBeNull()
    expect(cutoverParams({ device_id: 1 })).toBeNull()
    expect(cutoverParams({ device_id: 1, to: 'x', interface_map: null, on_conflict: 'keep', extra: 1 })).toEqual({ device_id: 1, to: 'x', on_conflict: 'keep' })
  })

  it('gap rows: one per start line, secrets skipped, AI syntax kept', () => {
    const rows = gapRows([
      { kind: 'raw', key: 'k', lines: [9], params: { text: 'dcn' } },
      { kind: 'node', key: 'k', schema: 'a.b', lines: [4], ai: { suggestion_id: 7, kind: 'equivalent', config: 'x' } },
      { kind: 'node', key: 'k', lines: [4] },
      { kind: 'node', key: 'k', lines: [5], params: { reason: 'secret' } },
      { kind: 'node', key: 'k', lines: [] },
    ])
    expect(rows.map((r) => r.line)).toEqual([4, 9])
    expect(rows[0].ai?.suggestion_id).toBe(7)
    expect(rows[1].text).toBe('dcn')
    expect(aiLineSet([3, 4]).has(4)).toBe(true)
  })

  it('section state and doc language', () => {
    const p = (status: string) => ({ suggestion_id: 1, status, text: '', steps: [] })
    expect(sectionState({ section: 's', title: '', parts: [] })).toBe('missing')
    expect(sectionState({ section: 's', title: '', parts: [p('pending')] })).toBe('pending')
    expect(sectionState({ section: 's', title: '', parts: [p('pending'), p('adopted')] })).toBe('adopted')
    expect(docLang('zh-CN')).toBe('zh-CN')
    expect(docLang('pt-BR')).toBe('en')
  })

  it('template extraction needs 1-10 devices of one family', () => {
    expect(templateReady([], [])).toBe(false)
    expect(templateReady([1, 2], ['a', 'a'])).toBe(true)
    expect(templateReady([1, 2], ['a', 'b'])).toBe(false)
  })
})
