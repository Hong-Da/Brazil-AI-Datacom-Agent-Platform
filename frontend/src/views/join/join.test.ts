import { describe, expect, it } from 'vitest'
import { inviteUrl, refSeg, splitMatch, statusIcon, tokenFrom } from './join'

describe('加入项目（M9-8）的纯函数', () => {
  it('项目路径段：属主/标识写成 属主~标识', () => {
    expect(refSeg('alice/lab')).toBe('alice~lab')
    expect(refSeg('lab')).toBe('lab')
  })
  it('邀请链接的完整地址', () => {
    expect(inviteUrl('/invite/lmi_x', 'http://10.0.0.8:9090/')).toBe('http://10.0.0.8:9090/invite/lmi_x')
  })
  it('从链接或令牌里取令牌', () => {
    expect(tokenFrom(' http://h:9090/invite/lmi_abc?x=1 ')).toBe('lmi_abc')
    expect(tokenFrom('lmi_abc')).toBe('lmi_abc')
  })
  it('搜索高亮', () => {
    expect(splitMatch('Campus core', 'CORE')).toEqual(['Campus ', 'core', ''])
    expect(splitMatch('abc', 'x')).toEqual(['abc', '', ''])
    expect(splitMatch('abc', '')).toEqual(['abc', '', ''])
  })
  it('状态图标', () => {
    expect(statusIcon('pending')).toBe('clock')
    expect(statusIcon('revoked')).toBe('x')
  })
})
