import { describe, expect, it } from 'vitest'
import { kbDetail, reportScope, type Suggestion } from './logic'

function sug(over: Partial<Suggestion>): Suggestion {
  return {
    id: 1, batch_id: 1, skill: 'x', category: 'kb_review', kind: '', title: '', content: {}, original: null, edited: false,
    refs: [], check: {}, check_status: 'pass', status: 'pending', kb: true, connection: '', created_by: '', created_at: null,
    decided_by: '', decided_at: null, adopt_info: null, note: '', reverted_by: '', reverted_at: null, device_id: null, scope_key: '',
    ...over,
  }
}

describe('M8-5 kbDetail', () => {
  it('rule draft with sample run', () => {
    const d = kbDetail(sug({ content: { review_kind: 'rule', payload: { yaml: 'id: a' } }, check: { result: { trial: { samples: 2, applicable: 3, samples_applicable: 1, hits: 1, samples_hit: 1, items: [] } } as never } }))
    expect(d.kind).toBe('rule')
    if (d.kind === 'rule') { expect(d.yaml).toBe('id: a'); expect(d.trial?.hits).toBe(1) }
  })
  it('unknown card shows base label and reparse', () => {
    const d = kbDetail(sug({ kind: 'variant', refs: [{ id: 'k1', found: true, label: 'huawei-vrp8.mtu' }], content: { review_kind: 'unknown_card', target: 'huawei-vrp8.mtu', payload: { cause: 'variant', base: 'k1', card: { syntax: 'mtu <n>' } } }, check: { result: { reparse: { lines: 2, recognized: 2 } } as never } }))
    expect(d).toMatchObject({ kind: 'unknown_card', cause: 'variant', base: 'huawei-vrp8.mtu', cardText: 'syntax: mtu <n>', reparse: { lines: 2, recognized: 2 } })
  })
  it('card maps and sanitize rule', () => {
    const m = kbDetail(sug({ content: { review_kind: 'card_maps', target: 'c', payload: { maps: { 'interface.mtu': '$m' } } }, check: { result: { checks: { kb: 'pass' } } as never } }))
    expect(m).toMatchObject({ kind: 'card_maps', maps: [{ node: 'interface.mtu', expr: '$m' }], checks: { kb: 'pass' } })
    const s = kbDetail(sug({ category: 'sanitize_rule', content: { line: 4, text: 'ZhangSan', kind: 'person' }, check: { result: { pattern: 'ZhangSan', occurrences: 2 } as never } }))
    expect(s).toMatchObject({ kind: 'sanitize', line: 4, text: 'ZhangSan', pattern: 'ZhangSan', occurrences: 2, sanKind: 'person' })
    expect(kbDetail(sug({ content: { review_kind: 'suggestion', payload: { a: 1 } } })).kind).toBe('other')
  })
})

describe('M8-5 reportScope (same as backend scope_key)', () => {
  it('builds scopes', () => {
    expect(reportScope('check', { device_id: 3 })).toBe('report:check:3')
    expect(reportScope('check', {})).toBeNull()
    expect(reportScope('baseline', { device_ids: [5, 2, 5], baseline: 'strict' })).toBe('report:baseline:strict:2,5')
    expect(reportScope('baseline', { device_ids: [] })).toBeNull()
    expect(reportScope('compare', { a: { device_id: 1 }, b: { version_id: 9 } })).toBe('report:compare:d1:v9')
    expect(reportScope('change', { current: { device_id: 1 }, target: {} })).toBeNull()
  })
})
