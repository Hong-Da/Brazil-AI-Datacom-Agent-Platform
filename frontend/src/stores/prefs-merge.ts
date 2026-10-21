/** 个人偏好登录时的合并（REQ-047）：纯逻辑，prefs-sync.ts 使用。 */
import type { Lang } from '@/i18n'
import type { AskIntro, IconSetPref, Theme } from '@/stores/prefs'

export interface AccountPrefs { lang?: Lang; theme?: Theme; term_style?: string; icon_set?: IconSetPref; ask_intro?: AskIntro }

export const PREF_KEYS = ['lang', 'theme', 'term_style', 'icon_set', 'ask_intro'] as const

/** 登录时的合并：apply 是要用到界面上的账号值，push 是要写入账号的本地值（都可能为空）。 */
export function mergeOnLogin(local: AccountPrefs, account: AccountPrefs | null): { apply: AccountPrefs; push: AccountPrefs | null } {
  if (!account || !Object.keys(account).length) return { apply: {}, push: pick(local) }
  // 账号里缺的项（例如以前没选过显示风格）用本地值补上
  const missing = pick(Object.fromEntries(PREF_KEYS.filter((k) => !(k in account)).map((k) => [k, local[k]])) as AccountPrefs)
  return { apply: account, push: Object.keys(missing).length ? missing : null }
}

export function pick(p: AccountPrefs): AccountPrefs {
  const out: AccountPrefs = {}
  for (const k of PREF_KEYS) if (p[k]) (out as Record<string, string>)[k] = p[k] as string
  return out
}
