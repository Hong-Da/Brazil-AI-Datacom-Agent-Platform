import { describe, expect, it } from 'vitest'
import { baseMark, checkState, filterScripts, nextScriptName, starterChange, type ProjDevice, type ScriptRow } from './logic'

const row = (o: Partial<ScriptRow> = {}): ScriptRow => ({
  id: 1, project_id: 1, name: 'a.txt', kind: 'change', lines: 3, revisions: 1, last_check: null,
  created_at: null, updated_at: null, group: { id: 1, name: 'g' },
  baseline: { device: { id: 7, name: 'R1', vendor: 'huawei', profile: 'p' }, version_id: null, follows_latest: true },
  order_check: true, ai_check: false, author: 'u', ...o,
})
const dev = (o: Partial<ProjDevice> = {}): ProjDevice => ({ id: 7, name: 'R1', vendor: 'huawei', profile: 'p', versions: 3, latest_version_id: 30, source: 'private', ...o })

describe('scripts logic', () => {
  it('filters by kind and baseline device', () => {
    const rows = [row({ id: 1 }), row({ id: 2, kind: 'full' }), row({ id: 3, baseline: null })]
    expect(filterScripts(rows, { kind: '', device: null }).map((r) => r.id)).toEqual([1, 2, 3])
    expect(filterScripts(rows, { kind: 'full', device: null }).map((r) => r.id)).toEqual([2])
    expect(filterScripts(rows, { kind: '', device: 7 }).map((r) => r.id)).toEqual([1, 2])
  })

  it('marks the baseline: private latest, public pinned by the project, script-pinned version', () => {
    expect(baseMark(row(), dev(), {})).toEqual({ source: 'private', policy: 'follow', seq: 3, latestSeq: 3, newer: false })
    expect(baseMark(row(), dev({ source: 'public', policy: 'pin', pinned_seq: 1, newer_available: true }), {}))
      .toEqual({ source: 'public', policy: 'pin', seq: 1, latestSeq: 3, newer: true })
    expect(baseMark(row(), dev({ source: 'public', policy: 'pin', pinned_version_id: 21 }), { 21: 2 })?.seq).toBe(2)
    expect(baseMark(row(), dev({ source: 'public', policy: 'follow' }), {})?.policy).toBe('follow')
    const pinned = row({ baseline: { device: { id: 7, name: 'R1', vendor: 'huawei', profile: 'p' }, version_id: 20, follows_latest: false } })
    expect(baseMark(pinned, dev(), { 20: 2 })).toMatchObject({ policy: 'pin', seq: 2 })
    expect(baseMark(row({ baseline: null }), dev(), {})).toBeNull()
  })

  it('check state, starter content and next name', () => {
    expect(checkState(null)).toBe('never')
    expect(checkState({ errors: 0, warnings: 0, infos: 0, order: true, kind: 'change', at: '' })).toBe('ok')
    expect(checkState({ errors: 1, warnings: 0, infos: 0, order: true, kind: 'change', at: '' })).toBe('issues')
    expect(starterChange('cisco')).toContain('configure terminal')
    expect(starterChange('huawei-atn')).toContain('system-view')
    expect(starterChange('nokia', 'nokia-sros-classic-7750-25.10')).toContain('exit all')
    expect(starterChange('nokia', 'nokia-sros-md-7750-25.10')).toContain('edit-config private')
    expect(nextScriptName([{ name: 'script-2.txt' }])).toBe('script-3.txt')
    expect(nextScriptName([{ name: 'x' }, { name: 'script-2.txt' }])).toBe('script-3.txt')
  })
})
