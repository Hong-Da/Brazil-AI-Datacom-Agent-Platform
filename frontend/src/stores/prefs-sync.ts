import { watch } from 'vue'
import { get, put } from '@/api'
import { useAuth } from '@/stores/auth'
import { usePrefs } from '@/stores/prefs'
import { mergeOnLogin, pick, type AccountPrefs } from '@/stores/prefs-merge'

/**
 * 个人偏好随账号保存（REQ-047，D-0325）：
 * - 未登录：浏览器本地的值（prefs 自己存 localStorage）。
 * - 登录后：账号保存过就以账号为准；没保存过就把本地值写入账号。
 * - 登录状态下修改：本地照常保存，另外约 0.5 秒后写入账号（连续切换只写最后一次）。
 * - 全局 API 令牌没有账号、只读个人令牌不能写：只用本地值（只读令牌仍读取账号的值）。
 */
interface PrefsResp { has_account: boolean; prefs: AccountPrefs | null }

export const SAVE_DELAY = 500

/** 在 App 里调用一次：跟随登录状态同步偏好。 */
export function startPrefsSync(): void {
  const auth = useAuth()
  const prefs = usePrefs()
  let mode: 'off' | 'rw' | 'ro' = 'off'
  let applying = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let gen = 0

  const local = (): AccountPrefs => ({ lang: prefs.lang, theme: prefs.theme, term_style: prefs.termStyle || undefined, icon_set: prefs.iconSet })
  function apply(p: AccountPrefs): void {
    applying = true
    if (p.lang) prefs.lang = p.lang
    if (p.theme) prefs.theme = p.theme
    if (p.term_style) prefs.termStyle = p.term_style
    if (p.icon_set) prefs.iconSet = p.icon_set
    // 让 watch 回调先跑完再放开（它们在同一轮里排队）
    queueMicrotask(() => { applying = false })
  }
  async function save(p: AccountPrefs): Promise<void> {
    prefs.syncState = 'saving'
    try { await put('/me/prefs', p); prefs.syncState = 'saved' } catch { prefs.syncState = 'error' }
  }

  async function attach(): Promise<void> {
    const my = ++gen
    const me = auth.me
    if (!me || me.via === 'token') { mode = 'off'; prefs.syncState = 'local'; return }
    let r: PrefsResp
    try { r = await get<PrefsResp>('/me/prefs') } catch { mode = 'off'; prefs.syncState = 'local'; return }
    if (my !== gen) return
    if (!r.has_account) { mode = 'off'; prefs.syncState = 'local'; return }
    const { apply: a, push } = mergeOnLogin(local(), r.prefs)
    apply(a)
    mode = me.read_only ? 'ro' : 'rw'
    prefs.syncState = mode === 'ro' ? 'local' : 'saved'
    if (push && mode === 'rw') await save(push)
  }

  watch(() => (auth.me ? `${auth.me.username}|${auth.me.via}` : ''), () => { clearTimeout(timer); void attach() }, { immediate: true })
  watch(() => [prefs.lang, prefs.theme, prefs.termStyle, prefs.iconSet], () => {
    if (applying || mode !== 'rw') return
    clearTimeout(timer)
    prefs.syncState = 'saving'
    timer = setTimeout(() => { void save(pick(local())) }, SAVE_DELAY)
  })
}
