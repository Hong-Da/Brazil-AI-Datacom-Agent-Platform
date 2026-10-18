import { describe, expect, it } from 'vitest'
import {
  acceptFile, filterDevices, fmtBytes, fmtTime, importTotals, sanitizedEntries, vendorCounts,
  type Device, type ImportFileResult,
} from './logic'

const dev = (o: Partial<Device>): Device => ({
  id: 1, name: 'R1', vendor: 'huawei', sw_version: 'V800R023', profile: 'huawei-atn-v800r023', versions: 1,
  latest_version_id: 1, source_name: 'r1.cfg', collected_at: '2026-10-18T00:43:48', lines: 10, parsed: true,
  unknown: 0, roundtrip: true, kb_version: '0.1.0', stale: false, ...o,
})
const list = [
  dev({ id: 1 }),
  dev({ id: 2, name: 'PE-ASR', vendor: 'cisco', profile: 'cisco-iosxe-asr920-17.15', roundtrip: false }),
  dev({ id: 3, name: 'B', stale: true, unknown: 2 }),
  dev({ id: 4, name: 'X', vendor: '', parsed: false, roundtrip: undefined }),
]

describe('设备筛选', () => {
  it('关键词匹配名称、Profile、版本、文件名', () => {
    expect(filterDevices(list, { q: 'asr920', vendor: '', state: '' }).map((d) => d.id)).toEqual([2])
    expect(filterDevices(list, { q: 'R1.CFG', vendor: '', state: '' }).length).toBe(4)
  })
  it('厂商与状态', () => {
    expect(filterDevices(list, { q: '', vendor: 'cisco', state: '' }).map((d) => d.id)).toEqual([2])
    expect(filterDevices(list, { q: '', vendor: '', state: 'fail' }).map((d) => d.id)).toEqual([2])
    expect(filterDevices(list, { q: '', vendor: '', state: 'stale' }).map((d) => d.id)).toEqual([3])
    expect(filterDevices(list, { q: '', vendor: '', state: 'err' }).map((d) => d.id)).toEqual([4])
    expect(filterDevices(list, { q: '', vendor: '', state: 'unknown' }).map((d) => d.id)).toEqual([3])
  })
  it('厂商计数按数量排序', () => {
    expect(vendorCounts(list)).toEqual([['huawei', 2], ['', 1], ['cisco', 1]])
  })
})

describe('导入', () => {
  it('只接受配置文本与 zip', () => {
    expect(acceptFile('a.cfg')).toBe(true)
    expect(acceptFile('dir/show-run')).toBe(true)
    expect(acceptFile('A.ZIP')).toBe(true)
    expect(acceptFile('README.md')).toBe(false)
    expect(acceptFile('.hidden.cfg')).toBe(false)
  })
  it('脱敏类别按固定顺序、跳过 0；汇总', () => {
    expect(sanitizedEntries({ ip: 7, secret: 20, user: 0 })).toEqual([['secret', 20], ['ip', 7]])
    const r = (o: Partial<ImportFileResult>): ImportFileResult => ({
      source: 'a', ok: true, device: 'd', vendor: 'huawei', version: '', profile: '', lines: 1, version_id: 1,
      sanitized: {}, unknown: 0, coverage: 1, error: '', ...o,
    })
    expect(importTotals([r({ sanitized: { ip: 2 }, unknown: 1 }), r({ ok: false })])).toEqual({ files: 2, ok: 1, failed: 1, replacements: 2, unknown: 1 })
  })
  it('格式化', () => {
    expect(fmtBytes(500)).toBe('500 B')
    expect(fmtBytes(2048)).toBe('2 KB')
    expect(fmtBytes(3 * 1024 * 1024)).toBe('3.0 MB')
    expect(fmtTime('2026-10-18T00:43:48')).toBe('10-18 00:43')
    expect(fmtTime('2026-10-18T00:43:48', true)).toBe('2026-10-18 00:43')
    expect(fmtTime(null)).toBe('')
  })
})
