import { describe, expect, it } from 'vitest'
import { buildOps, classifyImport, inProject, matchDevice, predictName, summarize, type ProjDevice, type PubDevice } from './logic'

const pub = (id: number, name: string, extra: Partial<PubDevice> = {}): PubDevice => ({
  id, name, vendor: 'huawei', sw_version: 'V8', profile: 'p', versions: 2, latest_version_id: 10 + id, collected_at: null, refs: [], follow: 0, pinned: 0, ...extra,
})
const dev = (id: number, name: string): ProjDevice => ({ id, name, vendor: 'huawei', profile: 'p', versions: 1, latest_version_id: id })

describe('add-device logic', () => {
  it('inProject: 已引用（同编号）或同名', () => {
    const here = [dev(4, 'PUB-A'), dev(7, 'atn01')]
    expect(inProject(pub(4, 'PUB-A'), here)).toBe('ref')
    expect(inProject(pub(5, 'ATN01'), here)).toBe('name')
    expect(inProject(pub(6, 'x'), here)).toBeNull()
  })

  it('predictName 与后端一致：同名加 -2、-3', () => {
    expect(predictName('atn01', [])).toBe('atn01')
    expect(predictName('atn01', ['ATN01'])).toBe('atn01-2')
    expect(predictName('atn01', ['atn01', 'atn01-2'])).toBe('atn01-3')
  })

  it('buildOps：先引用后复制，跟随最新不带版本，改名才传 name', () => {
    const p = [pub(1, 'a'), pub(2, 'b'), pub(3, 'c')]
    const ops = buildOps(
      p,
      { 1: { mode: 'copy', policy: 'pin', versionId: 11 }, 2: { mode: 'ref', policy: 'follow', versionId: 12 }, 3: { mode: 'ref', policy: 'pin', versionId: 13 } },
      'lab',
      [dev(20, 'x'), dev(21, 'y')],
      { 20: { versionId: null, name: 'x' }, 21: { versionId: 5, name: 'y-copy' } },
    )
    expect(ops.map((o) => [o.kind, o.deviceId, o.versionId, o.name])).toEqual([
      ['ref', 2, null, undefined],
      ['ref', 3, 13, undefined],
      ['copy', 1, 11, undefined],
      ['copy', 20, null, undefined],
      ['copy', 21, 5, 'y-copy'],
    ])
    expect(summarize(ops, 2)).toEqual({ refFollow: 1, refPin: 1, copies: 3, files: 2 })
  })

  it('buildOps：没有来源项目时忽略项目选择', () => {
    expect(buildOps([], {}, null, [dev(1, 'x')], { 1: { versionId: null, name: 'x' } })).toEqual([])
  })

  it('classifyImport：新设备 / 新版本 / 相同 / 失败，同批同名第二个算新版本', () => {
    const r = classifyImport(
      [
        { source: 'a.cfg', ok: true, device: 'NEW' },
        { source: 'b.cfg', ok: true, device: 'atn01' },
        { source: 'c.cfg', ok: true, device: 'atn01', duplicate: true },
        { source: 'd.cfg', ok: false, device: '', error: 'x' },
        { source: 'e.cfg', ok: true, device: 'new' },
      ],
      [dev(1, 'ATN01')],
    )
    expect(r).toEqual(['new', 'version', 'duplicate', 'failed', 'version'])
  })

  it('matchDevice 不区分大小写', () => {
    expect(matchDevice({ name: 'PE-ASR', profile: 'cisco-x' }, 'asr')).toBe(true)
    expect(matchDevice({ name: 'PE-ASR', profile: 'cisco-x' }, 'huawei')).toBe(false)
    expect(matchDevice({ name: 'PE', profile: 'p' }, ' ')).toBe(true)
  })
})
