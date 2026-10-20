import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import text from '@/i18n/pages/ai-suggest.json'
import type { SkillList } from './logic'

// 技能列表接口：由测试决定何时返回，用来复现“列表还没取回就点了主按钮”
let release: (v: SkillList) => void = () => {}
vi.mock('@/api', () => ({ get: vi.fn(() => new Promise<SkillList>((r) => { release = r })) }))
vi.mock('@/stores/project', () => ({ useProject: () => ({ ref: 'default' }) }))

const { default: AiEntryButton } = await import('./AiEntryButton.vue')
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': { 'ai-suggest': text['zh-CN'] } } })
const LIST: SkillList = {
  ai: { configured: true, reason: null, warn_tokens: 0 },
  skills: [{ id: 'device-summary', enabled: true, title: { 'zh-CN': '设备摘要' }, description: {} } as unknown as SkillList['skills'][number]],
}
const flush = async (): Promise<void> => { for (let i = 0; i < 3; i++) await Promise.resolve(); await nextTick() }

afterEach(() => { document.body.innerHTML = '' })

describe('AiEntryButton', () => {
  it('技能列表未取回时点主按钮：等列表回来后运行主 skill，而不是只展开菜单', async () => {
    const w = mount(AiEntryButton, { props: { skills: ['device-summary'] }, global: { plugins: [i18n], stubs: { AiOffHint: true } }, attachTo: document.body })
    await w.get('[data-testid="ai-entry-main"]').trigger('click')
    await flush()
    expect(w.emitted('run')).toBeUndefined()
    release(LIST)
    await flush()
    expect(w.emitted('run')).toEqual([['device-summary']])
    expect(w.find('[data-testid="ai-entry-menu"]').exists()).toBe(false)
    w.unmount()
  })

  it('AI 未配置时点主按钮展开原因提示', async () => {
    const w = mount(AiEntryButton, { props: { skills: ['device-summary'] }, global: { plugins: [i18n], stubs: { AiOffHint: true } }, attachTo: document.body })
    release({ ...LIST, ai: { configured: false, reason: 'not_configured', warn_tokens: 0 } })
    await flush()
    await w.get('[data-testid="ai-entry-main"]').trigger('click')
    await flush()
    expect(w.emitted('run')).toBeUndefined()
    expect(w.find('[data-testid="ai-entry-menu"]').exists()).toBe(true)
    w.unmount()
  })
})
