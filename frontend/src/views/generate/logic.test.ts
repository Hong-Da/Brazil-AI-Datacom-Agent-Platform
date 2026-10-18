import { describe, expect, it } from 'vitest'
import { alignCsv, cellErrors, exampleRow, parseCsv, reportMd, resultCsvRows, stages, toCsvText, type GenResult, type GenRow } from './logic'
import { crc32, zipBytes } from '@/views/m3/zip'
import { fill, msg } from '@/views/m3/texts'

const okRow = (i: number): GenRow => ({
  index: i, device: `PE-${i}`, ok: true, text: 'hostname X\n', params: {}, errors: [],
  checks: { parse: { profile: 'p', unknown: 0, unknown_lines: [] }, roundtrip: true, template: { compliant: true, errors: 0, findings: [], mismatched: [] } },
  file: `PE-${i}.cfg`,
})
const badRow: GenRow = {
  index: 2, device: 'PE-C', ok: false, text: null, params: {}, file: 'PE-C.cfg', checks: {},
  errors: [
    { stage: 'params', var: 'loopback', value: '10.9.0.32', problem: 'template.value.not_within' },
    { stage: 'params', var: 'svc', value: null, problem: 'template.param.count_mismatch' },
  ],
}

describe('CSV', () => {
  it('解析引号、逗号与换行，去掉 BOM 与空行', () => {
    expect(parseCsv('﻿a,b\r\n"x,1","y ""q"""\n\n1,\n')).toEqual([['a', 'b'], ['x,1', 'y "q"'], ['1', '']])
  })
  it('写出后再读入不变', () => {
    const t = toCsvText(['a', 'b'], [['1,2', 'x'], ['', 'z']])
    expect(parseCsv(t)).toEqual([['a', 'b'], ['1,2', 'x'], ['', 'z']])
  })
  it('按表头对齐模板的列', () => {
    const a = alignCsv([['hostname', 'device', 'zzz'], ['R1', 'd1', 'q']], ['device', 'hostname', 'asn'])
    expect(a).toEqual({ rows: [['d1', 'R1', '']], ignored: ['zzz'], missing: ['asn'] })
  })
  it('示例行', () => {
    expect(exampleRow(['device', 'hostname', 'opt', 'svc.vlan'], [
      { name: 'hostname', type: 'word', block: null, derived: false, example: 'PE-1' },
      { name: 'svc.vlan', type: 'vlan', block: 'svc', derived: false, example: 101 },
    ], [{ name: 'opt', kind: 'optional' }, { name: 'svc', kind: 'repeat' }])).toEqual(['PE-1', 'PE-1', 'true', '101'])
  })
})

describe('结果', () => {
  it('单元格错误：变量列与块的各列', () => {
    const m = cellErrors(badRow, ['device', 'loopback', 'svc.vlan', 'svc.lan'], 'en')
    expect([...m.keys()]).toEqual(['loopback', 'svc.vlan', 'svc.lan'])
    expect(m.get('loopback')![0]).toContain('10.9.0.32')
  })
  it('验证阶段：参数失败时后面跳过', () => {
    expect(stages(badRow, 'zh-CN').map((s) => s.state)).toEqual(['bad', 'skip', 'skip', 'skip', 'skip'])
    expect(stages(okRow(0), 'zh-CN').map((s) => s.state)).toEqual(['ok', 'ok', 'ok', 'ok', 'ok'])
    const cross = { ...okRow(0), checks: { ...okRow(0).checks, template: null } }
    expect(stages(cross, 'en')[4]).toMatchObject({ state: 'skip', note: 'cross' })
  })
  it('报告与带结果的参数表', () => {
    const res: GenResult = { template: { id: 't', version: 1, profile: 'p' }, engine: 'text', profile: 'p', verify: true, rows: [okRow(0), okRow(1), badRow], summary: { total: 3, ok: 2, failed: 1 } }
    expect(reportMd(res, 'en', 'T')).toContain('Rows: 3, passed: 2, failed: 1')
    expect(reportMd(res, 'zh-CN', 'T')).toContain('# 批量生成报告')
    const rows = resultCsvRows(['device'], [['PE-0'], ['PE-1'], ['PE-C']], res, 'en')
    expect(rows[1]).toEqual(['PE-0', 'passed', 'PE-0.cfg', ''])
    expect(rows[3][1]).toBe('failed')
  })
})

describe('ZIP 与文案', () => {
  it('CRC32 与 ZIP 结构', () => {
    expect(crc32(new TextEncoder().encode('123456789'))).toBe(0xcbf43926)
    const z = zipBytes([{ name: 'a.cfg', text: 'hello' }, { name: '中文.md', text: 'x' }], new Date(2026, 9, 18, 10, 0, 0))
    const dv = new DataView(z.buffer)
    expect(dv.getUint32(0, true)).toBe(0x04034b50)
    const end = z.length - 22
    expect(dv.getUint32(end, true)).toBe(0x06054b50)
    expect(dv.getUint16(end + 10, true)).toBe(2)
    expect(new TextDecoder().decode(z.slice(30, 35))).toBe('a.cfg')
  })
  it('后端文案键按语言渲染，未登记的键原样显示', () => {
    expect(msg('template.value.not_within', {}, 'en')).not.toBe('template.value.not_within')
    expect(msg('no.such.key', {}, 'en')).toBe('no.such.key')
    expect(fill('{a} {b}', { a: [1, 2] })).toBe('1, 2 {b}')
  })
})
