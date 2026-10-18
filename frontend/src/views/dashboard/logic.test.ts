import { describe, expect, it } from 'vitest'
import { diffLines, filterRt, profileView, rtState, sampleName, type RtResult } from './logic'

const base: RtResult = { file: 'a/x.cfg', gate: true, passed: true, ok: true, lines: 3, unknown: 0, diffs: [] }

describe('首页：样本往返', () => {
  it('状态：一致、不一致、门槛样本有未识别行、样本缺失', () => {
    expect(rtState(base)).toBe('pass')
    expect(rtState({ ...base, ok: false, passed: false })).toBe('diff')
    expect(rtState({ ...base, passed: false, unknown: 2 })).toBe('unknown')
    expect(rtState({ file: 'm', gate: true, ok: false, error: 'missing' })).toBe('missing')
  })
  it('仅未通过筛选', () => {
    const rs = [base, { ...base, file: 'b', ok: false, passed: false }]
    expect(filterRt(rs, '').length).toBe(2)
    expect(filterRt(rs, 'fail').map((r) => r.file)).toEqual(['b'])
  })
  it('样本名取文件名', () => {
    expect(sampleName('cisco-ios-public/batfish.txt')).toBe('batfish.txt')
  })
  it('差异行：原文带行号、渲染行无行号，前导空白拆出', () => {
    const ls = diffLines([{ line: 7, original: ['   mtu 9180', 'x'], rendered: [' mtu 9180'] }])
    expect(ls).toEqual([
      { kind: 'del', no: 7, ws: '   ', text: 'mtu 9180' },
      { kind: 'del', no: 8, ws: '', text: 'x' },
      { kind: 'add', no: null, ws: ' ', text: 'mtu 9180' },
    ])
  })
})

describe('首页：Profile', () => {
  it('覆盖率与可信度占比，合计 100', () => {
    const v = profileView({ id: 'p', vendor: 'cisco', inherits: null, own_entries: 82, entries: 82, coverage: 0.8817, credibility: { draft: 76, reviewed: 6, verified: 0 } })
    expect(v.vendor).toBe('cs')
    expect(v.pct).toBe(88)
    expect(v.unfilled).toBe(false)
    expect(v.cred.verified + v.cred.reviewed + v.cred.draft).toBe(100)
  })
  it('没有自有条目也不继承时为未填写；继承的不算', () => {
    const empty = { id: 'p', vendor: 'huawei', inherits: null, own_entries: 0, entries: 0, coverage: 0, credibility: { draft: 0, reviewed: 0, verified: 0 } }
    expect(profileView(empty).unfilled).toBe(true)
    expect(profileView(empty).cred).toEqual({ verified: 0, reviewed: 0, draft: 0 })
    expect(profileView({ ...empty, inherits: 'x', entries: 89 }).unfilled).toBe(false)
  })
})
