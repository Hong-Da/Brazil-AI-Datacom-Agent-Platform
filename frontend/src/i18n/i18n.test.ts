import { describe, expect, it } from 'vitest'
import zhCN from './zh-CN.json'
import en from './en.json'
import ptBR from './pt-BR.json'
import { pageMessages } from './index'

describe('界面文案', () => {
  it('三种语言的键完全一致', () => {
    const zh = Object.keys(zhCN).sort()
    expect(Object.keys(en).sort()).toEqual(zh)
    expect(Object.keys(ptBR).sort()).toEqual(zh)
  })
  it('没有空文案', () => {
    for (const m of [zhCN, en, ptBR]) for (const v of Object.values(m)) expect(String(v).trim()).not.toBe('')
  })
  it('页面文案三种语言的键一致且不为空', () => {
    const p = pageMessages()
    const zh = Object.keys(p['zh-CN']).sort()
    expect(Object.keys(p.en).sort()).toEqual(zh)
    expect(Object.keys(p['pt-BR']).sort()).toEqual(zh)
    for (const lang of ['zh-CN', 'en', 'pt-BR'] as const)
      for (const [k, v] of Object.entries(p[lang])) expect(String(v).trim(), `${lang} ${k}`).not.toBe('')
  })
})
