import { describe, expect, it } from 'vitest'
import { commentPrefix, isNokiaMd, starterScript, stripVendor, vendorKey, vendorMark, vendorName } from './vendor'

describe('厂商识别（M7-5 加 Nokia）', () => {
  it('厂商、平台族、Profile 都按前缀识别', () => {
    expect(vendorKey('huawei')).toBe('huawei')
    expect(vendorKey('cisco-iosxe-asr920-17.15')).toBe('cisco')
    expect(vendorKey('nokia-sros-md')).toBe('nokia')
    expect(vendorKey('Nokia')).toBe('nokia')
    expect(vendorKey('juniper')).toBe('')
    expect(vendorKey(null)).toBe('')
  })

  it('界面标记', () => {
    expect(vendorMark('nokia')).toEqual({ key: 'nokia', cls: 'nk', abbr: 'NK', letter: 'N', name: 'Nokia' })
    expect(vendorMark('huawei-vrp8')).toMatchObject({ cls: 'hw', abbr: 'HW', letter: 'H' })
    expect(vendorMark('cisco')).toMatchObject({ cls: 'cs', abbr: 'CS', letter: 'C' })
    expect(vendorMark('juniper')).toMatchObject({ key: '', cls: '', abbr: 'JU', letter: 'J', name: 'juniper' })
    expect(vendorMark('')).toMatchObject({ cls: '', abbr: '?', letter: '?' })
    expect(vendorName('nokia-sros-classic')).toBe('Nokia')
  })

  it('Nokia Classic / MD-CLI 的区分', () => {
    expect(isNokiaMd('nokia-sros-md')).toBe(true)
    expect(isNokiaMd('nokia', 'nokia-sros-md-7750-25.10')).toBe(true)
    expect(isNokiaMd('nokia-sros-classic-7750-25.10')).toBe(false)
    expect(isNokiaMd('nokia')).toBe(false)
  })

  it('空脚本骨架：华为 system-view … commit，Cisco configure terminal … end，Nokia Classic exit all / configure，MD-CLI edit-config', () => {
    expect(starterScript('huawei')).toBe('system-view\n\ncommit\n')
    expect(starterScript('cisco-iosxe')).toBe('configure terminal\n\nend\n')
    expect(starterScript('nokia', 'nokia-sros-classic-7750-25.10')).toBe('exit all\nconfigure\n\nexit all\n')
    expect(starterScript('nokia', 'nokia-sros-md-7750-25.10')).toBe('edit-config private\n\ncommit\nquit-config\n')
    // 只知道厂商是 Nokia 时用 Classic；什么都不知道时用华为
    expect(starterScript('nokia')).toBe('exit all\nconfigure\n\nexit all\n')
    expect(starterScript(undefined, '')).toBe('system-view\n\ncommit\n')
  })

  it('注释前缀与简称', () => {
    expect(commentPrefix('cisco-iosxe')).toBe('!')
    expect(commentPrefix('nokia-sros-md')).toBe('#')
    expect(commentPrefix('huawei-vrp8')).toBe('#')
    expect(stripVendor('nokia-sros-md-7750-25.10')).toBe('sros-md-7750-25.10')
  })
})
