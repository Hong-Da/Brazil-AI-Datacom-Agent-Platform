import { describe, expect, it } from 'vitest'
import { blankRules, copyId, issueAt, move, newNameRule, normalize, renamedLines, reportCounts, titleOf, toSave, validId, type NamingReport } from './logic'

const rep = (over: Partial<NamingReport> = {}): NamingReport => ({
  rule_set: 't', family: 'cisco-iosxe', ports: [], conflicts: [], naming: [], text_refs: [], gaps: [],
  renames: [
    { type: 'vrf.instance', node: 'vrf.instance[RAN]', new_node: 'vrf.instance[VRF_RAN]', from: 'RAN', to: 'VRF_RAN', mapped: 'VRF_RAN', rule: { section: 'names', index: 0 }, naming_rule: null, fixes: [], refs: 2, ref_nodes: [], applied: true, conflict: null, lines: [1] },
    { type: 'vrf.instance', node: 'vrf.instance[OAM]', new_node: null, from: 'OAM', to: 'X', mapped: 'X', rule: null, naming_rule: 0, fixes: ['upper'], refs: 0, ref_nodes: [], applied: false, conflict: 'many_to_one', lines: [] },
  ],
  summary: { renamed: 1, refs: 2, ports: 0, subinterfaces: 0, conflicts: 1, naming: 0, text_refs: 0, gaps: 0 },
  ...over,
})

describe('translate-rules logic', () => {
  it('moves rules within bounds', () => {
    expect(move([1, 2, 3], 0, 1)).toEqual([2, 1, 3])
    expect(move([1, 2, 3], 0, -1)).toEqual([1, 2, 3])
    expect(move([1, 2, 3], 2, 1)).toEqual([1, 2, 3])
  })
  it('validates ids and suggests copy ids', () => {
    expect(validId('atn-to-asr920')).toBe(true)
    expect(validId('bad id')).toBe(false)
    expect(validId('-x')).toBe(false)
    expect(copyId('a', [])).toBe('a-copy')
    expect(copyId('a', ['a-copy', 'a-copy-2'])).toBe('a-copy-3')
  })
  it('normalizes partial rules and drops empty rows on save', () => {
    const r = normalize({ id: 'x', names: [{ match: 'regex', from: 'a', to: 'b' } as never], naming: [{ type: 'rp.policy' } as never] })
    expect(r.names[0].enabled).toBe(true)
    expect(r.naming[0].replace).toEqual([])
    r.names.push(newNameRule())
    const s = toSave(r)
    expect(s.names).toHaveLength(1)
    expect('id' in s).toBe(false)
    expect(blankRules('k').id).toBe('k')
  })
  it('locates issues', () => {
    expect(issueAt('names[2].from')).toEqual({ section: 'names', index: 2, field: 'from' })
    expect(issueAt('id')).toEqual({ section: 'id', index: null, field: '' })
  })
  it('finds lines with applied new names only', () => {
    const lines = ['vrf definition VRF_RAN', ' vrf forwarding VRF_RAN_X', 'vrf definition X', 'ip route vrf VRF_RAN 0.0.0.0 0.0.0.0 1.1.1.1']
    expect([...renamedLines(lines, rep())]).toEqual([0, 3])
    expect(renamedLines(lines, null).size).toBe(0)
  })
  it('counts report items', () => {
    expect(reportCounts(rep())).toEqual({ renamed: 1, skipped: 1, refs: 2, ports: 0, conflicts: 0, naming: 0 })
  })
  it('picks the title for the language', () => {
    expect(titleOf({ id: 'a', title: { en: 'A', 'zh-CN': '甲' } }, 'en')).toBe('A')
    expect(titleOf({ id: 'a', title: { 'zh-CN': '甲' } }, 'pt-BR')).toBe('甲')
    expect(titleOf({ id: 'a' }, 'en')).toBe('a')
  })
})
