import { describe, expect, it } from 'vitest'
import { applyBulk, scopeList, scopeVendors, vendorLabel } from './ask-scope'

const devs = [
  { name: 'SMAIA01-RMP01', vendor: 'cisco', profile: 'cisco-iosxe-asr920-17.15' },
  { name: 'SMAIAR2-RMD01', vendor: 'huawei', profile: 'huawei-atn-v800r025' },
  { name: 'SMAUJ02-RMP02', vendor: '', profile: '' },
  { name: 'PE-7750-01', vendor: 'nokia', profile: 'nokia-sros-classic' },
]

describe('AI 查询范围（REQ-051）', () => {
  it('厂商按华为、Cisco、Nokia 排序，不含只存原文的设备', () => {
    expect(scopeVendors(devs)).toEqual(['huawei', 'cisco', 'nokia'])
  })
  it('按设备名筛选不区分大小写，只存原文的设备也能搜到', () => {
    expect(scopeList(devs, 'smauj', '').map((d) => d.name)).toEqual(['SMAUJ02-RMP02'])
    expect(scopeList(devs, '  ', '')).toHaveLength(4)
  })
  it('按厂商筛选时不出现只存原文的设备', () => {
    expect(scopeList(devs, '', 'cisco').map((d) => d.name)).toEqual(['SMAIA01-RMP01'])
    expect(scopeList(devs, 'rm', 'huawei').map((d) => d.name)).toEqual(['SMAIAR2-RMD01'])
  })
  it('厂商显示名首字母大写', () => {
    expect(vendorLabel('huawei')).toBe('Huawei')
    expect(vendorLabel('')).toBe('')
  })
  it('全选、清空、反选只作用于筛出来的设备', () => {
    const scope = ['A', 'B', 'X']
    expect(applyBulk(scope, ['A', 'C'], 'all').sort()).toEqual(['A', 'B', 'C', 'X'])
    expect(applyBulk(scope, ['A', 'C'], 'none').sort()).toEqual(['B', 'X'])
    expect(applyBulk(scope, ['A', 'C'], 'invert').sort()).toEqual(['B', 'C', 'X'])
    expect(applyBulk([], ['A'], 'invert')).toEqual(['A'])
  })
})
