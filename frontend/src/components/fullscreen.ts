/**
 * 视图全屏（REQ-043）的逻辑：浏览器全屏优先，不可用或被拒绝时退回页面内最大化。
 *
 * - 只切换容器的显示方式、不重建内容，所以缩放、选中、滚动位置自然保留；
 *   图形组件用 ResizeObserver 跟随容器尺寸，这里在切换后再派发一次 resize 兜底。
 * - 快捷键：F 进入 / 退出（输入框聚焦、有对话框打开时不触发），Esc 退出
 *   （浏览器全屏的 Esc 由浏览器处理，页面内最大化由这里处理）。
 * - 一页有多个全屏区域时，F 作用于已全屏的那个；都没全屏时作用于最后注册的、可见的那个。
 * - localStorage `lmesh-fs` = `max` 时强制页面内最大化（测试与不支持浏览器全屏的环境用）。
 */
import { ref, shallowRef, type InjectionKey, type Ref } from 'vue'

export type FsMode = '' | 'native' | 'max'

export interface FsPane {
  el: () => HTMLElement | null
  mode: Ref<FsMode>
  /** false 时不响应 F 键（按钮仍可用）。 */
  shortcut: () => boolean
  enter: () => Promise<void>
  exit: () => Promise<void>
  toggle: () => Promise<void>
  /** 由全局监听调用：浏览器全屏状态变化后同步 mode。 */
  sync: () => void
}

const FORCE_KEY = 'lmesh-fs'
/** FullscreenPane 提供给区域内 FullscreenButton 的控制器。 */
export const FS_KEY: InjectionKey<FsPane> = Symbol('fullscreen')
const panes: FsPane[] = []

export function forceMax(): boolean {
  try { return localStorage.getItem(FORCE_KEY) === 'max' } catch { return false }
}

function nativeOk(el: HTMLElement): boolean {
  return !forceMax() && !!document.fullscreenEnabled && typeof el.requestFullscreen === 'function'
}

/** 正在输入（F 不触发全屏）。CodeMirror 的编辑区是 contenteditable。 */
export function isTyping(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null
  if (!el || !el.tagName) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable || !!el.closest?.('[contenteditable="true"]')
}

/** 有对话框打开时快捷键交给对话框（Esc 关闭对话框，而不是退出全屏）。 */
function modalOpen(): boolean {
  return !!document.querySelector('.modal-back')
}

/**
 * 当前全屏的元素（没有全屏时为 null）。区域外的对话框、提示用
 * `<Teleport :to="fsTarget ?? 'body'" :disabled="!fsTarget">` 挂进去，否则全屏时看不到。
 */
export const fsTarget = shallowRef<HTMLElement | null>(null)

function syncTarget(): void {
  const p = activePane()
  fsTarget.value = p ? p.el() : null
  document.body.classList.toggle('has-fs-max', panes.some((x) => x.mode.value === 'max'))
}

/** 弹出层、提示的挂载点：全屏时挂在全屏元素里，否则挂在 body（挂在外面会被全屏层盖住）。 */
export function fsHost(): HTMLElement {
  const fs = document.fullscreenElement as HTMLElement | null
  if (fs) return fs
  const max = panes.find((p) => p.mode.value === 'max')?.el()
  return max ?? document.body
}

function visible(el: HTMLElement | null): boolean {
  return !!el && el.isConnected && el.getClientRects().length > 0
}

export function activePane(): FsPane | undefined {
  return panes.find((p) => p.mode.value !== '')
}

function onKey(e: KeyboardEvent): void {
  if (e.defaultPrevented || modalOpen()) return
  if (e.key === 'Escape') {
    const p = panes.find((x) => x.mode.value === 'max')
    if (p) { e.preventDefault(); void p.exit() }
    return
  }
  if ((e.key === 'f' || e.key === 'F') && !e.ctrlKey && !e.metaKey && !e.altKey && !isTyping(e.target)) {
    const target = activePane() ?? [...panes].reverse().find((p) => p.shortcut() && visible(p.el()))
    if (!target) return
    e.preventDefault()
    void target.toggle()
  }
}

function onFsChange(): void {
  for (const p of panes) p.sync()
}

function register(p: FsPane): void {
  if (!panes.length) {
    document.addEventListener('keydown', onKey)
    document.addEventListener('fullscreenchange', onFsChange)
  }
  panes.push(p)
}

function unregister(p: FsPane): void {
  const i = panes.indexOf(p)
  if (i >= 0) panes.splice(i, 1)
  if (!panes.length) {
    document.removeEventListener('keydown', onKey)
    document.removeEventListener('fullscreenchange', onFsChange)
  }
}

/** 切换后通知图形组件重算尺寸（ResizeObserver 之外的兜底，例如只监听 window resize 的组件）。 */
function relayout(): void {
  requestAnimationFrame(() => window.dispatchEvent(new Event('resize')))
}

/**
 * 建一个全屏区域。返回的 dispose 在组件卸载时调用（会先退出全屏）。
 * onChange 在进入 / 退出后调用（mode 为新状态）。
 */
export function createFsPane(el: () => HTMLElement | null, opts: { shortcut?: () => boolean; onChange?: (m: FsMode) => void } = {}): FsPane & { dispose: () => void } {
  const mode = ref<FsMode>('')
  const set = (m: FsMode): void => {
    if (mode.value === m) return
    mode.value = m
    syncTarget()
    relayout()
    opts.onChange?.(m)
  }
  const pane: FsPane = {
    el,
    mode,
    shortcut: opts.shortcut ?? (() => true),
    async enter() {
      const node = el()
      if (!node || mode.value) return
      if (nativeOk(node)) {
        try {
          await node.requestFullscreen()
          set('native')
          return
        } catch { /* 被拒绝（没有用户手势、iframe 不允许等）：退回页面内最大化 */ }
      }
      set('max')
    },
    async exit() {
      const node = el()
      if (mode.value === 'native' && node && document.fullscreenElement === node) {
        try { await document.exitFullscreen() } catch { /* 已退出 */ }
      }
      set('')
    },
    async toggle() {
      if (mode.value) await pane.exit()
      else await pane.enter()
    },
    sync() {
      const node = el()
      if (mode.value === 'native' && (!node || document.fullscreenElement !== node)) set('')
      else if (!mode.value && node && document.fullscreenElement === node) set('native')
    },
  }
  register(pane)
  return {
    ...pane,
    dispose() {
      if (mode.value === 'native' && document.fullscreenElement === el()) void document.exitFullscreen().catch(() => undefined)
      mode.value = ''
      unregister(pane)
      syncTarget()
    },
  }
}
