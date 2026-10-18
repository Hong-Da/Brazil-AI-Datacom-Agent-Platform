import { describe, expect, it } from 'vitest'
import { isLangText, localizeParams, noteText } from './note'

const N = { 'zh-CN': '接口引用 ACL', en: 'Interface references the ACL', 'pt-BR': 'A interface referencia a ACL' }

describe('依赖说明 note', () => {
  it('三语字典按语言取值', () => {
    expect(noteText(N, 'zh-CN')).toBe('接口引用 ACL')
    expect(noteText(N, 'en')).toBe('Interface references the ACL')
    expect(noteText(N, 'pt-BR')).toBe('A interface referencia a ACL')
  })
  it('缺少的语言回退英文、中文', () => {
    expect(noteText({ 'zh-CN': '中', en: 'E' }, 'pt-BR')).toBe('E')
    expect(noteText({ 'zh-CN': '中' }, 'en')).toBe('中')
  })
  it('字符串原样返回，空值为空串', () => {
    expect(noteText('peer_group', 'en')).toBe('peer_group')
    expect(noteText('', 'en')).toBe('')
    expect(noteText(null, 'en')).toBe('')
    expect(noteText(undefined, 'en')).toBe('')
    expect(noteText({}, 'en')).toBe('')
  })
  it('只认语言键组成的对象', () => {
    expect(isLangText(N)).toBe(true)
    expect(isLangText({})).toBe(true)
    expect(isLangText({ name: 'x' })).toBe(false)
    expect(isLangText(['a'])).toBe(false)
    expect(isLangText('a')).toBe(false)
  })
  it('文案参数中的三语文本换成对应语言，其他参数不变', () => {
    expect(localizeParams({ a: 'x', note: N, key: { name: 'A' }, n: 3 }, 'pt-BR')).toEqual({
      a: 'x', note: 'A interface referencia a ACL', key: { name: 'A' }, n: 3,
    })
    expect(localizeParams(undefined, 'en')).toEqual({})
  })
})

describe('文案参数中的三语说明', () => {
  it('检查发现与 M3 / M4 文案按语言代入 note', async () => {
    const { renderText } = await import('@/views/check/logic')
    const texts = { 'x.msg': { 'zh-CN': '互斥：{note}', en: 'Mutex: {note}', 'pt-BR': 'Exclusão: {note}' } }
    expect(renderText({ key: 'x.msg', params: { note: N } }, 'en', texts, new Map())).toBe('Mutex: Interface references the ACL')
    expect(renderText({ key: 'x.msg', params: { note: N } }, 'pt-BR', texts, new Map())).toBe('Exclusão: A interface referencia a ACL')
    const m4 = await import('@/views/m4/texts')
    expect(m4.msg('x.msg', { note: N }, 'zh-CN', texts)).toBe('互斥：接口引用 ACL')
  })
})
