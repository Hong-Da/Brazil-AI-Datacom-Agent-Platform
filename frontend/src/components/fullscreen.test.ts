import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import FullscreenPane from './FullscreenPane.vue'
import FullscreenButton from './FullscreenButton.vue'
import { createFsPane, fsHost, fsTarget, isTyping } from './fullscreen'
import fsText from '@/i18n/pages/fullscreen.json'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': { fullscreen: fsText['zh-CN'] }, en: { fullscreen: fsText.en }, 'pt-BR': { fullscreen: fsText['pt-BR'] } },
})

function key(k: string, target: EventTarget = document.body, opts: KeyboardEventInit = {}): KeyboardEvent {
  const e = new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...opts })
  target.dispatchEvent(e)
  return e
}
const flush = async (): Promise<void> => { for (let i = 0; i < 3; i++) await Promise.resolve(); await nextTick() }

/** jsdom 的 getClientRects 总是空的：让已连接的元素算作可见。 */
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, 'getClientRects').mockImplementation(function (this: HTMLElement) {
    return (this.isConnected ? [{}] : []) as unknown as DOMRectList
  })
  localStorage.removeItem('lmesh-fs')
})
afterEach(() => {
  vi.restoreAllMocks()
  document.body.innerHTML = ''
  Object.defineProperty(document, 'fullscreenEnabled', { configurable: true, value: undefined })
})

describe('isTyping', () => {
  it('输入框、文本框、下拉框、可编辑区算正在输入', () => {
    for (const tag of ['input', 'textarea', 'select']) expect(isTyping(document.createElement(tag))).toBe(true)
    const ce = document.createElement('div'); ce.setAttribute('contenteditable', 'true')
    const inner = document.createElement('span'); ce.appendChild(inner); document.body.appendChild(ce)
    expect(isTyping(inner)).toBe(true)
    expect(isTyping(document.createElement('button'))).toBe(false)
    expect(isTyping(null)).toBe(false)
  })
})

describe('createFsPane', () => {
  it('浏览器全屏不可用时退回页面内最大化，Esc 与 F 都能退出', async () => {
    const el = document.createElement('div'); document.body.appendChild(el)
    const onChange = vi.fn()
    const p = createFsPane(() => el, { onChange })
    key('f'); await flush()
    expect(p.mode.value).toBe('max')
    expect(fsTarget.value).toBe(el)
    expect(fsHost()).toBe(el)
    expect(document.body.classList.contains('has-fs-max')).toBe(true)
    key('Escape'); await flush()
    expect(p.mode.value).toBe('')
    expect(fsTarget.value).toBe(null)
    expect(fsHost()).toBe(document.body)
    key('F'); await flush(); expect(p.mode.value).toBe('max')
    key('f'); await flush(); expect(p.mode.value).toBe('')
    expect(onChange.mock.calls.map((c) => c[0])).toEqual(['max', '', 'max', ''])
    p.dispose()
  })

  it('输入框聚焦、带修饰键、有对话框时 F 不触发', async () => {
    const el = document.createElement('div'); document.body.appendChild(el)
    const input = document.createElement('input'); el.appendChild(input)
    const p = createFsPane(() => el)
    key('f', input); key('f', document.body, { ctrlKey: true }); await flush()
    expect(p.mode.value).toBe('')
    const modal = document.createElement('div'); modal.className = 'modal-back'; document.body.appendChild(modal)
    key('f'); await flush()
    expect(p.mode.value).toBe('')
    modal.remove()
    await p.enter()
    document.body.appendChild(modal)
    key('Escape'); await flush()
    expect(p.mode.value).toBe('max') // Esc 先关对话框
    p.dispose()
  })

  it('优先浏览器全屏；被拒绝时退回页面内最大化；强制开关走页面内最大化', async () => {
    Object.defineProperty(document, 'fullscreenEnabled', { configurable: true, value: true })
    let fsEl: Element | null = null
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => fsEl })
    const el = document.createElement('div'); document.body.appendChild(el)
    el.requestFullscreen = vi.fn(async () => { fsEl = el; document.dispatchEvent(new Event('fullscreenchange')) })
    document.exitFullscreen = vi.fn(async () => { fsEl = null; document.dispatchEvent(new Event('fullscreenchange')) })
    const p = createFsPane(() => el)
    await p.enter()
    expect(p.mode.value).toBe('native')
    expect(fsHost()).toBe(el)
    // 浏览器自己处理 Esc：只发 fullscreenchange
    fsEl = null; document.dispatchEvent(new Event('fullscreenchange'))
    expect(p.mode.value).toBe('')
    await p.toggle(); expect(p.mode.value).toBe('native')
    await p.toggle(); expect(p.mode.value).toBe('')
    expect(document.exitFullscreen).toHaveBeenCalled()

    el.requestFullscreen = vi.fn(async () => { throw new Error('denied') })
    await p.enter(); expect(p.mode.value).toBe('max')
    await p.exit()

    localStorage.setItem('lmesh-fs', 'max')
    el.requestFullscreen = vi.fn(async () => undefined)
    await p.enter()
    expect(el.requestFullscreen).not.toHaveBeenCalled()
    expect(p.mode.value).toBe('max')
    p.dispose()
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: null })
  })

  it('多个区域：F 作用于最后注册的可见区域；已全屏的优先退出', async () => {
    const a = document.createElement('div'); const b = document.createElement('div')
    document.body.append(a, b)
    const pa = createFsPane(() => a)
    const pb = createFsPane(() => b, { shortcut: () => false })
    key('f'); await flush()
    expect(pa.mode.value).toBe('max') // b 关闭了快捷键
    expect(pb.mode.value).toBe('')
    key('f'); await flush()
    expect(pa.mode.value).toBe('')
    pa.dispose(); pb.dispose()
  })
})

describe('FullscreenPane', () => {
  it('按钮切换全屏，内容不重建，卸载时退出', async () => {
    let mounted = 0
    const Child = defineComponent({ setup() { mounted++; return () => h('p', 'content') } })
    const w = mount(
      defineComponent({ setup: () => () => h(FullscreenPane, { title: 'T' }, { default: () => [h(FullscreenButton), h(Child)] }) }),
      { global: { plugins: [i18n] }, attachTo: document.body },
    )
    const root = w.find('.fsv')
    const btn = w.find('[data-testid="fs-btn"]')
    expect(root.attributes('data-fs')).toBe('off')
    expect(btn.text()).toContain('全屏')
    expect(btn.find('kbd').text()).toBe('F')
    expect(btn.attributes('title')).toContain('（F）')
    await btn.trigger('click'); await flush()
    expect(root.attributes('data-fs')).toBe('max')
    expect(root.classes()).toContain('is-fs')
    expect(root.classes()).toContain('is-max')
    expect(w.find('.fs-title').text()).toBe('T')
    expect(btn.attributes('aria-pressed')).toBe('true')
    expect(btn.find('kbd').text()).toBe('Esc')
    expect(w.find('[data-testid="fs-hint"]').classes()).toContain('on')
    key('Escape'); await flush()
    expect(root.attributes('data-fs')).toBe('off')
    expect(mounted).toBe(1)
    await btn.trigger('click'); await flush()
    w.unmount()
    expect(fsTarget.value).toBe(null)
    expect(document.body.classList.contains('has-fs-max')).toBe(false)
  })

  it('三种语言的文案键一致且不为空', () => {
    const keys = Object.keys(fsText['zh-CN']).sort()
    for (const l of ['en', 'pt-BR'] as const) {
      expect(Object.keys(fsText[l]).sort()).toEqual(keys)
      for (const v of Object.values(fsText[l])) expect(v).not.toBe('')
    }
  })
})
