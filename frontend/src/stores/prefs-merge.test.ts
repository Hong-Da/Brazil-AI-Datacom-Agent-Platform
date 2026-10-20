import { describe, expect, it } from 'vitest'
import { mergeOnLogin } from './prefs-merge'

describe('个人偏好登录时的合并（REQ-047）', () => {
  const local = { lang: 'en' as const, theme: 'dark' as const, term_style: 'cisco', icon_set: 'line' as const }
  it('账号没保存过：全部本地值写入账号，界面不变', () => {
    expect(mergeOnLogin(local, null)).toEqual({ apply: {}, push: local })
    expect(mergeOnLogin(local, {})).toEqual({ apply: {}, push: local })
  })
  it('账号保存过：以账号为准，不写回', () => {
    const acc = { lang: 'pt-BR' as const, theme: 'light' as const, term_style: 'nokia', icon_set: 'geo' as const }
    expect(mergeOnLogin(local, acc)).toEqual({ apply: acc, push: null })
  })
  it('账号缺的项用本地值补上（例如以前没选过显示风格）', () => {
    const acc = { lang: 'pt-BR' as const }
    expect(mergeOnLogin(local, acc)).toEqual({ apply: acc, push: { theme: 'dark', term_style: 'cisco', icon_set: 'line' } })
  })
  it('本地没选过显示风格时不写空值', () => {
    expect(mergeOnLogin({ lang: 'en', theme: 'auto', term_style: undefined, icon_set: 'geo' }, null).push).toEqual({ lang: 'en', theme: 'auto', icon_set: 'geo' })
  })
})
