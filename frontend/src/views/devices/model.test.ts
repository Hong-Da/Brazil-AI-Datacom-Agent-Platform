import { describe, expect, it } from 'vitest'
import { batchHits, buildChoices, changed, condText, globMatch, hasCondition, initialChoice, isApprox, levelCounts, levelOf, options, pct, regexOk, unknownHigh, type Candidate, type InspectFile } from './model'
import { filterDevices, type Device } from './logic'

const cand = (profile: string, ratio: number, extra: Partial<Candidate> = {}): Candidate => ({
  profile, title: profile, vendor: 'huawei', family: 'huawei-vrp8', ratio, recognized: 0, command: 72, unknown: 2, unsupported: 0, exact: false, fallback: false, ...extra,
})
const ne = (n: string): InspectFile => ({
  source: `ne8000-x8-0${n}.cfg`, ok: true, error: '', device: `NE8000-X8-0${n}`, vendor: 'huawei', version: 'V800R022C10SPC300', lines: 100,
  profile: 'huawei-atn-v800r025', profile_source: 'fallback', match_level: 'approx',
  candidates: [cand('huawei-atn-v800r025', 0.973, { fallback: true }), cand('huawei-atn-v800r023', 0.973)], recommended: 'huawei-atn-v800r025',
  suggested_rule: { name_pattern: 'NE8000-X8-*', version: 'V800R022', feature: '' },
})
const atn: InspectFile = { ...ne('9'), source: 'atn.cfg', device: 'ATN-1', version: 'V800R025C00SPC500', profile_source: 'auto', match_level: 'exact' }
const edge: InspectFile = {
  source: 'edge.conf', ok: true, error: '', device: 'edge-mx-01', vendor: '', version: '', profile: '', profile_source: 'none', match_level: 'none',
  candidates: [cand('cisco-iosxe-asr920-17.15', 0.1), cand('huawei-atn-v800r025', 0)], recommended: 'cisco-iosxe-asr920-17.15',
}

describe('匹配程度与来源（REQ-044）', () => {
  it('来源 → 匹配程度；近似 = 厂商默认、型号规则、手工', () => {
    expect(['auto', 'fallback', 'rule', 'manual', 'none', ''].map(levelOf)).toEqual(['exact', 'approx', 'approx', 'approx', 'none', 'none'])
    expect(isApprox('rule')).toBe(true)
    expect(isApprox('auto')).toBe(false)
    expect(pct(0.0364)).toBe('3.6%')
    expect(pct(null)).toBe('—')
    expect(unknownHigh(0.05)).toBe(true)
    expect(unknownHigh(0.049)).toBe(false)
    expect(levelCounts([ne('1'), atn, edge, { source: 'x', ok: false, error: 'e' }])).toEqual({ exact: 1, approx: 1, none: 1 })
  })
  it('下拉候选：认得厂商时标推荐，认不出时不标', () => {
    expect(options(ne('1')).map((o) => [o.profile, o.recommended])).toEqual([['huawei-atn-v800r025', true], ['huawei-atn-v800r023', false]])
    expect(options(edge).every((o) => !o.recommended)).toBe(true)
  })
})

describe('记住为型号规则', () => {
  it('设备名通配与正则检查', () => {
    expect(globMatch('NE8000-*', 'ne8000-x8-01')).toBe(true)
    expect(globMatch('NE8000-X?-01', 'NE8000-X8-01')).toBe(true)
    expect(globMatch('NE40E-*', 'NE8000-X8-01')).toBe(false)
    expect(globMatch('', 'any')).toBe(true)
    expect(regexOk('V800R0(22|23)')).toBe(true)
    expect(regexOk('(')).toBe(false)
    expect(hasCondition({ name_pattern: ' ', version: '', feature: '' })).toBe(false)
    expect(condText({ name_pattern: 'NE8000-*', version: 'V800R022', feature: '' })).toBe('NE8000-* · V800R022')
  })
  it('本批会命中的文件：同厂商、设备名与版本都满足', () => {
    const files = [ne('1'), ne('2'), atn, edge]
    expect(batchHits(files, { name_pattern: 'NE8000-*', version: 'V800R022', feature: '' }, 'huawei')).toEqual(['ne8000-x8-01.cfg', 'ne8000-x8-02.cfg'])
    expect(batchHits(files, { name_pattern: '', version: '(', feature: '' }, 'huawei')).toEqual([])
  })
})

describe('导入接口的 choices', () => {
  it('只写与自动不同的选择；记住时带规则；认不出厂商按处理方式', () => {
    const files = [ne('1'), ne('2'), atn, edge]
    const ch = Object.fromEntries(files.map((f) => [f.source, initialChoice(f)]))
    expect(changed(files[0], ch[files[0].source])).toBe(false)
    let out = buildChoices(files, ch)
    expect(out.choices).toEqual({ 'edge.conf': { raw_only: true } }) // 认不出厂商默认只存原文
    ch['ne8000-x8-01.cfg'].profile = 'huawei-atn-v800r023'
    ch['ne8000-x8-01.cfg'].remember = true
    ch['edge.conf'].unknown = 'skip'
    out = buildChoices(files, ch)
    expect(out.choices['ne8000-x8-01.cfg']).toEqual({ profile: 'huawei-atn-v800r023', remember: { scope: 'project', name_pattern: 'NE8000-X8-*', version: 'V800R022', feature: '' } })
    expect(out.choices['edge.conf']).toBeUndefined()
    expect(out.skip).toEqual(['edge.conf'])
    ch['edge.conf'].unknown = 'pick'
    ch['edge.conf'].profile = 'cisco-iosxe-asr920-17.15'
    expect(buildChoices(files, ch).choices['edge.conf']).toEqual({ profile: 'cisco-iosxe-asr920-17.15' })
    // 不改选只勾记住：也带上 Profile 与规则
    ch['ne8000-x8-02.cfg'].remember = true
    expect(buildChoices(files, ch).choices['ne8000-x8-02.cfg']?.remember?.name_pattern).toBe('NE8000-X8-*')
  })
  it('zip 里的文件按最后一段文件名', () => {
    const f = { ...ne('1'), source: 'batch.zip/ne8000-x8-01.cfg' }
    const ch = { [f.source]: { ...initialChoice(f), profile: 'huawei-atn-v800r023' } }
    expect(Object.keys(buildChoices([f], ch).choices)).toEqual(['ne8000-x8-01.cfg'])
  })
})

describe('设备筛选：近似与不支持的厂商', () => {
  const base = { sw_version: '', source_name: '', collected_at: null, latest_version_id: 1, versions: 1 }
  const list: Device[] = [
    { ...base, id: 1, name: 'NE', vendor: 'huawei', profile: 'p', approx: true, profile_source: 'fallback' },
    { ...base, id: 2, name: 'EDGE', vendor: '', profile: '', unsupported: true, profile_source: 'none' },
    { ...base, id: 3, name: 'ATN', vendor: 'huawei', profile: 'p', profile_source: 'auto' },
  ]
  it('按状态筛选', () => {
    expect(filterDevices(list, { q: '', vendor: '', state: 'approx' }).map((d) => d.id)).toEqual([1])
    expect(filterDevices(list, { q: '', vendor: '', state: 'unsupported' }).map((d) => d.id)).toEqual([2])
  })
})
