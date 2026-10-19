import { describe, expect, it } from 'vitest'
import { bySource, currentSeq, newerRefs, rowActions, stats, type ProjectDevice } from './project'

const base = { vendor: 'huawei', sw_version: '', profile: 'p', source_name: '', collected_at: null, latest_version_id: 1 }
const priv: ProjectDevice = { ...base, id: 1, name: 'A', versions: 3, source: 'private' }
const follow: ProjectDevice = { ...base, id: 2, name: 'B', versions: 2, source: 'public', policy: 'follow' }
const pinned: ProjectDevice = { ...base, id: 3, name: 'C', versions: 4, source: 'public', policy: 'pin', pinned_seq: 2, newer_available: true, public_latest_version_id: 9 }

describe('项目里的设备', () => {
  it('按来源筛选与统计', () => {
    const all = [priv, follow, pinned]
    expect(bySource(all, '').length).toBe(3)
    expect(bySource(all, 'private').map((d) => d.id)).toEqual([1])
    expect(bySource(all, 'public').map((d) => d.id)).toEqual([2, 3])
    expect(stats(all)).toEqual({ total: 3, private: 1, refs: 2, newer: 1 })
    expect(newerRefs(all).map((d) => d.id)).toEqual([3])
  })
  it('当前版本序号：固定的取固定版本，其余取版本数', () => {
    expect(currentSeq(priv)).toBe(3)
    expect(currentSeq(follow)).toBe(2)
    expect(currentSeq(pinned)).toBe(2)
  })
  it('行菜单按来源与权限', () => {
    expect(rowActions(priv, true)).toEqual(['rebuild', 'history', 'copyTo', 'delete'])
    expect(rowActions(priv, false)).toEqual(['history', 'copyTo'])
    expect(rowActions(follow, true)).toEqual(['pinLatest', 'copyPrivate', 'history', 'copyTo', 'unlink'])
    expect(rowActions(pinned, true)).toEqual(['follow', 'pinLatest', 'copyPrivate', 'history', 'copyTo', 'unlink'])
    expect(rowActions(pinned, false)).toEqual(['history', 'copyTo'])
  })
})
