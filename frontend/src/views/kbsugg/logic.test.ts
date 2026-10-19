import { describe, expect, it } from 'vitest'
import { buildPayload, diffOf, kindOf, meaningful, statusTag, type SuggestionItem } from './logic'

describe('kb suggestions', () => {
  it('builds payload and reports missing fields', () => {
    const ok = buildPayload({ target: ' vrf.instance.rd ', kind: 'default', current: '', proposed: ' 100:1 ', reason: ' doc ' }, 'oam')
    expect(ok.body).toEqual({ target: 'vrf.instance.rd', kind: 'default', current: '', proposed: '100:1', reason: 'doc', project: 'oam' })
    const bad = buildPayload({ target: ' ', kind: 'other', current: '', proposed: '', reason: '  ' }, null)
    expect(bad.body).toBeNull()
    expect(bad.missing).toEqual(['target', 'reason'])
  })
  it('maps status, kind and diff', () => {
    expect(statusTag('approved').cls).toBe('t-teal')
    expect(statusTag('rejected').key).toBe('st.rejected')
    expect(statusTag('pending').cls).toBe('t-amber')
    const it0: SuggestionItem = { id: 1, kind: 'suggestion', status: 'pending', title: '', target: 'x', source: null, note: '', created_at: null, decided_at: null, payload: { kind: 'syntax', current: ' a ', proposed: 'b' } }
    expect(kindOf(it0)).toBe('syntax')
    expect(diffOf(it0)).toEqual({ current: 'a', proposed: 'b' })
    expect(kindOf({ ...it0, payload: null })).toBe('other')
    expect(meaningful('—')).toBe(false)
    expect(meaningful('1500')).toBe(true)
  })
})

describe('editLink', () => {
  it('routes profile entries and schema nodes', async () => {
    const { editLink, canReject } = await import('./logic')
    expect(editLink('huawei-atn:vrf.instance.rd')).toEqual({ name: 'profiles', query: { profile: 'huawei-atn', node: 'vrf.instance.rd' } })
    expect(editLink('vrf.instance')).toEqual({ name: 'schema-edit', query: { node: 'vrf.instance' } })
    expect(canReject('  ')).toBe(false)
    expect(canReject('dup')).toBe(true)
  })
})
