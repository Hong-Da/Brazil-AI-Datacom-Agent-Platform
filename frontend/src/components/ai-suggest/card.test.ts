import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import text from '@/i18n/pages/ai-suggest.json'
import AiSuggestCard from './AiSuggestCard.vue'
import type { Suggestion } from './logic'

const i18n = (locale: 'zh-CN' | 'en' | 'pt-BR') => createI18n({ legacy: false, locale, missingWarn: false, fallbackWarn: false, messages: { [locale]: Object.fromEntries(Object.entries(text[locale]).map(([k, v]) => [`ai-suggest.${k}`, v])) } })
const sug = (p: Partial<Suggestion>): Suggestion => ({
  id: 1, batch_id: 1, skill: 'report-summary', category: 'text_only', kind: 'zh-CN', title: '检查结论', content: { text: 'x' }, original: null, edited: false, refs: [],
  check: { status: 'pass', reasons: [] }, check_status: 'pass', status: 'pending', kb: false, connection: '', created_by: '', created_at: null, decided_by: '', decided_at: null,
  adopt_info: null, note: '', reverted_by: '', reverted_at: null, device_id: null, scope_key: '', ...p,
} as unknown as Suggestion)
const title = (s: Suggestion, locale: 'zh-CN' | 'en' | 'pt-BR' = 'en') =>
  mount(AiSuggestCard, { props: { item: s, open: false, canWrite: true, canKb: true }, global: { plugins: [i18n(locale)] } }).find('.tl span:last-child').text()

describe('AiSuggestCard', () => {
  it('报告摘要的标题跟随界面语言，不显示 AI 写的中文标题（REQ-056-06）', () => {
    expect(title(sug({}))).toBe('Report summary · for the Chinese report')
    expect(title(sug({ kind: 'en', title: 'Summary' }), 'zh-CN')).toBe('报告摘要 · 英文报告用')
    expect(title(sug({ kind: 'en' }), 'pt-BR')).toBe('Resumo do relatório · para o relatório em inglês')
    // 其他技能仍显示 AI 标题
    expect(title(sug({ skill: 'device-summary', title: 'T1' }))).toBe('T1')
  })

  it('PE / P / CE 角色三种语言都给出说明，与其他角色一致翻译（REQ-056-06）', () => {
    for (const l of ['zh-CN', 'en', 'pt-BR'] as const) {
      for (const r of ['pe', 'p', 'ce']) expect(text[l][`role.${r}` as keyof (typeof text)[typeof l]]).toMatch(/^(PE|P|CE)[ （(]/)
    }
  })
})
