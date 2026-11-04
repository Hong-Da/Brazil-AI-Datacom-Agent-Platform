import { describe, expect, it, vi } from 'vitest'
import { defineComponent, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import type { ChangePlan } from './logic'

// 接口由测试决定何时返回：建议列表立即返回，计划请求按顺序挂起，用来复现“先发后到”
const plans: ((v: ChangePlan) => void)[] = []
vi.mock('@/api', () => ({
  errorText: (e: unknown) => String(e),
  get: vi.fn((url: string) => (url.includes('/ai/change/plan') ? new Promise<ChangePlan>((r) => plans.push(r)) : Promise.resolve({ items: [{ batch_id: 7 }] }))),
}))
vi.mock('@/stores/project', () => ({ useProject: () => ({ ref: 'default' }) }))

const { default: IntentPanel } = await import('./IntentPanel.vue')
const i18n = createI18n({ legacy: false, locale: 'en', missingWarn: false, fallbackWarn: false, messages: { en: {} } })
const Panel = defineComponent({ name: 'AiSuggestPanel', emits: ['changed', 'state'], template: '<div />' })
const flush = async (): Promise<void> => { for (let i = 0; i < 4; i++) await Promise.resolve(); await nextTick() }
const plan = (n: number): ChangePlan => ({ batch_id: 7, adopted: Array.from({ length: n }, (_, i) => i + 1), rows: Array.from({ length: n }, (_, i) => ({ text: `op${i + 1}`, k: 'ai', seq: i + 1 })), verify: true, rollback_verify: true })

describe('IntentPanel', () => {
  it('连续采纳两条时，先发后到的旧计划不覆盖新的（REQ-056-05）', async () => {
    const w = mount(IntentPanel, { props: { deviceId: 1 }, global: { plugins: [i18n], stubs: { AiSuggestPanel: Panel, AiEntryButton: true, 'router-link': true } } })
    await flush()
    plans.shift()!(plan(0))
    await flush()
    const p = w.findComponent(Panel)
    p.vm.$emit('changed') // 采纳第一条
    await flush()
    p.vm.$emit('changed') // 采纳第二条
    await flush()
    expect(plans.length).toBe(2)
    plans[1](plan(2)) // 新的先回来
    await flush()
    plans[0](plan(1)) // 旧的后回来
    await flush()
    expect(w.findAll('[data-testid="ai-intent-code"] .l').map((x) => x.find('.t').text())).toEqual(['op1', 'op2'])
    w.unmount()
  })
})
