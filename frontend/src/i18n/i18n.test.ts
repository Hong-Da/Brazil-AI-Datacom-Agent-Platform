import { describe, expect, it } from 'vitest'
import zhCN from './zh-CN.json'
import en from './en.json'
import ptBR from './pt-BR.json'

describe('界面文案', () => {
  it('三种语言的键完全一致', () => {
    const zh = Object.keys(zhCN).sort()
    expect(Object.keys(en).sort()).toEqual(zh)
    expect(Object.keys(ptBR).sort()).toEqual(zh)
  })
  it('没有空文案', () => {
    for (const m of [zhCN, en, ptBR]) for (const v of Object.values(m)) expect(String(v).trim()).not.toBe('')
  })
})
