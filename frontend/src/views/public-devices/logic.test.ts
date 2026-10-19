import { describe, expect, it } from 'vitest'
import type { PubDevice } from '../add-device/logic'
import { filterPublic, isFresh, publicStats, timeline } from './logic'

const NOW = Date.parse('2026-10-19T12:00:00Z')
const d = (id: number, at: string | null, refs: PubDevice['refs'] = []): PubDevice => ({
  id, name: `dev-${id}`, vendor: 'huawei', sw_version: 'V8', profile: 'huawei-atn', versions: 3, latest_version_id: 30 + id, collected_at: at, refs, follow: 0, pinned: 0,
})
const ref = (project: string, version_id: number | null) => ({ project, name: project, owner: 'u', policy: (version_id ? 'pin' : 'follow') as 'pin' | 'follow', version_id, seq: null })

describe('public-devices logic', () => {
  const list = [
    d(1, '2026-10-19T08:00:00Z', [ref('a', null), ref('b', 20)]),
    d(2, '2026-10-10T08:00:00Z', [ref('a', 32)]),
    d(3, null),
  ]

  it('isFresh：24 小时内', () => {
    expect(isFresh(list[0], NOW)).toBe(true)
    expect(isFresh(list[1], NOW)).toBe(false)
    expect(isFresh(list[2], NOW)).toBe(false)
  })

  it('filterPublic：新版本、没有被引用、关键词', () => {
    expect(filterPublic(list, '', 'fresh', NOW).map((x) => x.id)).toEqual([1])
    expect(filterPublic(list, '', 'unused', NOW).map((x) => x.id)).toEqual([3])
    expect(filterPublic(list, 'DEV-2', '', NOW).map((x) => x.id)).toEqual([2])
  })

  it('publicStats：被引用、项目数、固定在旧版本的引用', () => {
    expect(publicStats(list, NOW)).toEqual({ total: 3, referenced: 2, projects: 2, fresh: 1, pinnedOld: 1 })
  })

  it('timeline：新的在前，最新版本计跟随，旧版本计固定', () => {
    const rows = timeline(list[0], [
      { id: 20, seq: 1, collected_at: 'a' },
      { id: 31, seq: 2, collected_at: 'b' },
    ])
    expect(rows.map((r) => [r.seq, r.latest, r.follow, r.pinned])).toEqual([
      [2, true, 1, 0],
      [1, false, 0, 1],
    ])
  })
})
