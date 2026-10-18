import { describe, expect, it } from 'vitest'
import {
  bumpCounts, changeRows, changelog, diffCounts, fmtTime, fmtValue, nextVersion, regressionStale, releaseFailure,
  sortSamples, suggestVersion, type KbDiff,
} from './logic'

const empty: KbDiff = {
  nodes_added: [], nodes_removed: [], nodes_semantic: [], nodes_deprecated: [], cards_added: [], cards_removed: [],
  cards_changed: [], defaults_changed: [], profiles_added: [], suggested_bump: 'patch',
}

describe('知识库版本逻辑', () => {
  it('版本号升级规则与后端一致', () => {
    expect(nextVersion('0.1.0', 'patch')).toBe('0.1.1')
    expect(nextVersion('0.1.3', 'minor')).toBe('0.2.0')
    expect(nextVersion('0.9.3', 'major')).toBe('1.0.0')
    expect(nextVersion('1', 'patch')).toBe('1.0.1')
    expect(suggestVersion('0.1.0', '0.1.0', 'patch')).toBe('0.1.1')
    expect(suggestVersion(null, '0.0.0', 'minor')).toBe('0.1.0')
  })

  it('差异展开成表格行并按影响排序', () => {
    const d: KbDiff = {
      ...empty,
      nodes_added: ['bgp.af'],
      nodes_removed: ['x.old'],
      defaults_changed: [{ profile: 'huawei-atn-v800r023', node: 'interface.mtu', old: null, new: 9000 }],
      suggested_bump: 'major',
    }
    const rows = changeRows(d)
    expect(rows.map((r) => r.kind)).toEqual(['nodeRemoved', 'nodeAdded', 'defaultChanged'])
    expect(rows[2]).toMatchObject({ profile: 'huawei-atn-v800r023', old: null, new: 9000, bump: 'patch' })
    expect(bumpCounts(d)).toEqual({ major: 1, minor: 1, patch: 1 })
    expect(diffCounts(d).total).toBe(3)
    expect(diffCounts(null).total).toBe(0)
    expect(changeRows(null)).toEqual([])
  })

  it('值与时间格式化', () => {
    expect(fmtValue(null)).toBe('—')
    expect(fmtValue(9000)).toBe('9000')
    expect(fmtValue({ a: 1 })).toBe('{"a":1}')
    expect(fmtTime(0)).toMatch(/^19(69|70)-/)
    expect(fmtTime(null)).toBe('')
    expect(fmtTime('bad')).toBe('')
  })

  it('回归样本排序：门槛失败在前', () => {
    const s = sortSamples([
      { file: 'a', ok: true, passed: true },
      { file: 'b', ok: false, passed: false, gate: false },
      { file: 'c', ok: false, passed: false, gate: true },
    ])
    expect(s.map((x) => x.file)).toEqual(['c', 'b', 'a'])
  })

  it('回归结果早于最近修改时提示过时', () => {
    const reg = { samples: 1, failed: 0, results: [], at: '2026-10-18T00:00:00+00:00' }
    const t = Date.parse('2026-10-18T00:00:00Z') / 1000
    expect(regressionStale(reg, [{ commit: 'a', time: t + 10, message: '' }])).toBe(true)
    expect(regressionStale(reg, [{ commit: 'a', time: t - 10, message: '' }])).toBe(false)
    expect(regressionStale(null, [{ commit: 'a', time: t, message: '' }])).toBe(false)
  })

  it('变更日志按发布分组', () => {
    const releases = [
      { version: '0.2.0', tag: 'kb-v0.2.0', commit: 'bbbbbbbbbbbb1234', time: 3, message: 'second' },
      { version: '0.1.0', tag: 'kb-v0.1.0', commit: 'aaaaaaaaaaaa5678', time: 1, message: 'first' },
      { version: '0.0.9', tag: 'kb-v0.0.9', commit: 'zzzzzzzzzzzz0000', time: 0, message: 'old' },
    ]
    const history = [
      { commit: 'cccccccccccc', time: 4, message: 'draft edit' },
      { commit: 'bbbbbbbbbbbb', time: 3, message: '知识库 0.2.0' },
      { commit: 'dddddddddddd', time: 2, message: 'edit' },
      { commit: 'aaaaaaaaaaaa', time: 1, message: '知识库 0.1.0' },
      { commit: 'eeeeeeeeeeee', time: 0, message: 'init' },
    ]
    const log = changelog(releases, history)
    expect(log.map((e) => e.version)).toEqual([null, '0.2.0', '0.1.0', '0.0.9'])
    expect(log[0].commits.map((c) => c.message)).toEqual(['draft edit'])
    expect(log[1].commits.map((c) => c.message)).toEqual(['知识库 0.2.0', 'edit'])
    expect(log[2].commits.map((c) => c.message)).toEqual(['知识库 0.1.0', 'init'])
    expect(log[3].commits).toEqual([])
    expect(changelog([], [])).toEqual([])
  })

  it('发布失败原因', () => {
    expect(releaseFailure([{ level: 'error', code: 'x', message: 'm' }, { level: 'warning', code: 'y', message: 'w' }])).toEqual({
      type: 'invalid', issues: [{ level: 'error', code: 'x', message: 'm' }],
    })
    expect(releaseFailure({ samples: 1, failed: 1, results: [] }).type).toBe('regression')
    expect(releaseFailure('0.1.0')).toEqual({ type: 'exists', version: '0.1.0' })
    expect(releaseFailure(null)).toEqual({ type: 'other' })
  })
})
