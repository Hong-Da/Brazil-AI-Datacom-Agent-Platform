import { describe, expect, it } from 'vitest'
import type { Suggestion } from '@/components/ai-suggest/logic'
import { cardScope, gateBlocked, mapRows, mappingScope, sanitizeScope, triageMarks, triagePattern, UNKNOWN_SCOPE } from './logic'

function sug(p: Partial<Suggestion>): Suggestion {
  return {
    id: 1, batch_id: 1, skill: 'unknown-triage', category: 'kb_review', kind: 'missing', title: '', content: null, original: null, edited: false,
    refs: [], check: {}, check_status: 'pass', status: 'pending', kb: true, connection: '', created_by: '', created_at: null, decided_by: '',
    decided_at: null, adopt_info: null, note: '', reverted_by: '', reverted_at: null, device_id: null, scope_key: UNKNOWN_SCOPE, ...p,
  }
}
const tri = (id: number, group: string, cause: string, extra: Partial<Suggestion> = {}) => sug({
  id, content: { review_kind: 'unknown_card', target: 'x', payload: { group, cause } },
  refs: [{ id: 'u1', found: true, type: 'unknown', label: 'port-isolate enable group <n>' }, { id: 'u2', found: true, type: 'unknown', label: 'ptp clock-source local' }],
  ...extra,
})

describe('知识库 AI 接入逻辑', () => {
  it('scope 与后端一致', () => {
    expect(UNKNOWN_SCOPE).toBe('unknown-lines')
    expect(cardScope('huawei-vrp8.mtu')).toBe('card:huawei-vrp8.mtu')
    expect(mappingScope('cisco-iosxe')).toBe('mapping:cisco-iosxe')
    expect(sanitizeScope(3)).toBe('device:3')
  })

  it('建议按 group 找到写法', () => {
    expect(triagePattern(tri(1, 'u2', 'missing'))).toBe('ptp clock-source local')
    expect(triagePattern(sug({ refs: [{ id: 'u9', found: false }] }))).toBeNull()
  })

  it('归因标记：已送审优先，未通过与已忽略次之', () => {
    const m = triageMarks([
      tri(1, 'u1', 'missing', { check_status: 'reject' }),
      tri(2, 'u1', 'variant'),
      tri(3, 'u2', 'version', { status: 'adopted' }),
      tri(4, 'u2', 'missing', { status: 'dismissed' }),
      sug({ id: 5, skill: 'card-review' }),
    ])
    expect(m['port-isolate enable group <n>']).toEqual({ cause: 'variant', state: 'pending', id: 2 })
    expect(m['ptp clock-source local']).toEqual({ cause: 'version', state: 'sent', id: 3 })
    expect(Object.keys(m)).toHaveLength(2)
    expect(triageMarks([tri(1, 'u1', 'missing', { check_status: 'reject' })])['port-isolate enable group <n>'].state).toBe('fail')
  })

  it('映射建议表：每张卡取最新一条', () => {
    const r = mapRows([
      sug({ id: 1, skill: 'mapping-suggest', content: { review_kind: 'card_maps', target: 'c.mtu', payload: { maps: { 'interface.mtu': '{mtu}' } } } }),
      sug({ id: 2, skill: 'mapping-suggest', check_status: 'reject', content: { review_kind: 'card_maps', target: 'c.mtu', payload: { maps: { 'interface.description': '{x}' } } } }),
      sug({ id: 3, skill: 'mapping-suggest', status: 'adopted', content: { review_kind: 'card_maps', target: 'c.a', payload: { maps: { 'vrf.rd': '{rd}', 'vrf.name': '{n}' } } } }),
    ])
    expect(r).toEqual([
      { id: 3, card: 'c.a', nodes: ['vrf.rd', 'vrf.name'], state: 'sent' },
      { id: 2, card: 'c.mtu', nodes: ['interface.description'], state: 'fail' },
    ])
  })

  it('本地模型检查', () => {
    expect(gateBlocked(null)).toBe(false)
    expect(gateBlocked({ skill: 's', allowed: false, local_only: true, provider: 'openai', reason: 'local_only' })).toBe(true)
    expect(gateBlocked({ skill: 's', allowed: true, local_only: true, provider: 'local', reason: null })).toBe(false)
  })
})
