import { describe, expect, it } from 'vitest'
import {
  appendRaw, buildWarns, groupCounts, interfacesIn, interfacesInGraph, linkFromDst, linkFromSrc, outIndex, renameNode, reportMd, srcIndex,
  warnCsvRows, warnDst, warnText,
} from './logic'
import type { OutLine, TranslateResult, TrItem } from './types'

const item = (kind: string, node: string | null, lines: number[] = [], params: Record<string, unknown> = {}): TrItem => ({
  kind, key: `translate.warn.${kind}`, node, schema: null, lines, params: { node, ...params },
})
const ol = (no: number, text: string, nodes: string[] = [], origin = 'explicit', kind = 'command'): OutLine => ({ no, text, kind, origin, nodes, card: null })

const result = (): TranslateResult => ({
  source: { device: 'PE-1', profile: 'cisco-iosxe-asr920-17.15', family: 'cisco-iosxe' },
  target: { profile: 'huawei-atn-v800r025', family: 'huawei-vrp8' },
  interface_map: { 'GigabitEthernet0/0/1': 'GE0/2/1' },
  text: '',
  lines: [
    ol(1, 'interface GE0/2/1', ['interface[GE0/2/1]']),
    ol(2, ' mtu 9000', ['interface[GE0/2/1]/mtu']),
    ol(3, ' apply-label per-route', ['vrf.instance[A]/af[ipv4]/label_mode']),
    ol(4, 'return', [], 'explicit', 'end'),
  ],
  warnings: [
    item('default_differs', 'vrf.instance[A]/af[ipv4]/label_mode', [], { level: 'warning', src_default: 'per-route', dst_default: 'per-instance', profile: 'huawei-atn-v800r025' }),
    item('inferred_value', 'bgp.instance[1]/bgp.peer_group[RR]/type', [], { level: 'warning', value: 'internal', profile: 'x' }),
  ],
  unsupported: [
    { kind: 'raw', key: 'translate.unsupported.raw', node: 'raw[4]', schema: null, lines: [4], params: { text: 'version 17.15', line: 4 } },
    { kind: 'node', key: 'translate.unsupported.no_render', node: 'interface[GigabitEthernet0/0/1]/access[101]', schema: 'interface.access', lines: [7, 8], params: { schema: 'interface.access' } },
  ],
  defaults: [],
  stats: { facts: 10, rendered: 8, lines: 3, unsupported: 1, not_translated: 1, defaults_omitted: 0, default_differs: 1, default_unknown: 0, defaults_same: 0, warnings: 2 },
  verify: { checked: true, equal: false, diffs: 2, unexplained: 0 },
})

describe('告警分组', () => {
  it('按默认值、不支持、原文、推导排序并编号', () => {
    const ws = buildWarns(result())
    expect(ws.map((w) => [w.id, w.group])).toEqual([['W1', 'default'], ['W2', 'unsup'], ['W3', 'raw'], ['W4', 'infer']])
    expect(groupCounts(ws)).toEqual({ default: 1, unsup: 1, raw: 1, infer: 1 })
    expect(ws[2].level).toBe('info')
  })
  it('文案按语言渲染参数', () => {
    const ws = buildWarns(result())
    expect(warnText(ws[0], 'zh-CN')).toContain('per-instance')
    expect(warnText(ws[2], 'en')).toContain('version 17.15')
  })
})

describe('接口改名与行联动', () => {
  it('节点编号中的接口名按映射表改写，子接口也改', () => {
    const m = { 'GigabitEthernet0/0/1': 'GE0/2/1' }
    expect(renameNode('interface[GigabitEthernet0/0/1]/mtu', m)).toBe('interface[GE0/2/1]/mtu')
    expect(renameNode('interface[GigabitEthernet0/0/1.100]', m)).toBe('interface[GE0/2/1.100]')
    expect(renameNode('bgp.peer[update_source=GigabitEthernet0/0/1]', m)).toBe('bgp.peer[update_source=GE0/2/1]')
    expect(renameNode('interface[GE0/2/1]/mtu', m, true)).toBe('interface[GigabitEthernet0/0/1]/mtu')
    expect(renameNode('interface[GigabitEthernet0/0/10]', m)).toBe('interface[GigabitEthernet0/0/10]')
  })
  it('源行 → 译文行，译文行 → 源行；告警优先', () => {
    const r = result()
    const ws = buildWarns(r)
    const idx = outIndex(r.lines)
    const dstOf = (w: (typeof ws)[number]) => warnDst(w, idx, r.interface_map)
    expect(dstOf(ws[0])).toEqual([2])
    const { lineNodes, nodeLines } = srcIndex([
      { id: 'interface[GigabitEthernet0/0/1]', kind: 'object', lines: [5] },
      { id: 'interface[GigabitEthernet0/0/1]/mtu', kind: 'attr', lines: [6] },
      { id: 'device', kind: 'device', lines: [] },
    ])
    expect(linkFromSrc(6, ws, dstOf, lineNodes, idx, r.interface_map)).toEqual({ src: [6], dst: [1] })
    expect(linkFromSrc(4, ws, dstOf, lineNodes, idx, r.interface_map).warn).toBe('W3')
    expect(linkFromDst(1, r.lines, ws, dstOf, nodeLines, r.interface_map)).toEqual({ src: [6], dst: [1] })
    expect(linkFromDst(2, r.lines, ws, dstOf, nodeLines, r.interface_map).warn).toBe('W1')
  })
})

describe('附注与下载', () => {
  it('未翻译原文以注释附在 return 之前', () => {
    const r = result()
    const ws = buildWarns(r)
    const out = appendRaw(r.lines, ws, 'untranslated:')
    expect(out.map((l) => l.text)).toEqual(['interface GE0/2/1', ' mtu 9000', ' apply-label per-route', '! untranslated:', '!   version 17.15', 'return'])
    expect(out[4].warn).toBe('W3')
    expect(out.map((l) => l.no)).toEqual([1, 2, 3, 4, 5, 6])
  })
  it('告警 CSV 与双语报告', () => {
    const r = result()
    const ws = buildWarns(r)
    const rows = warnCsvRows(ws, (w) => warnDst(w, outIndex(r.lines), r.interface_map), 'en')
    expect(rows[0][0]).toBe('id')
    expect(rows[1].slice(0, 2)).toEqual(['W1', 'default'])
    expect(rows[1][7]).toBe('3')
    const zh = reportMd(r, ws, 'zh-CN', 'T')
    const en = reportMd(r, ws, 'en', 'T')
    expect(zh).toContain('# 配置翻译报告')
    expect(zh).toContain('GigabitEthernet0/0/1 → GE0/2/1')
    expect(en).toContain('2 differences, 0 unexplained')
  })
  it('从配置中列出接口', () => {
    expect(interfacesIn('interface GE0/2/1\n mtu 1\ninterface GE0/2/1.10\n#\ninterface LoopBack0')).toEqual(['GE0/2/1', 'GE0/2/1.10', 'LoopBack0'])
  })
  it('Nokia：从配置图的顶层接口对象列出接口（M7-5）', () => {
    const o = (id: string, schema: string, key: unknown) => ({ id, kind: 'object', schema, key })
    expect(interfacesInGraph([
      o('interface[1/1/4]', 'interface', '1/1/4'), o('interface[system]', 'interface', 'system'),
      o('interface[1/1/4]/access[1001]', 'interface.access', '1001'), o('vrf.instance[A]', 'vrf.instance', 'A'),
      { id: 'interface[1/1/4]/mtu', kind: 'attr', schema: 'interface.mtu' },
    ])).toEqual(['1/1/4', 'system'])
  })
})
