/** skill 详情页各标签页共用的状态（provide / inject）：详情、编辑中的草稿、回归集、提示条。 */
import { inject, type ComputedRef, type InjectionKey, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { pickLang } from '@/i18n'
import { stCls } from './logic'
import type { CasesResult, Definition, SkillDetail } from './types'

export interface SkillCtx {
  sid: ComputedRef<string>
  detail: Ref<SkillDetail | null>
  draft: Ref<Definition | null>
  dirty: ComputedRef<boolean>
  cases: Ref<CasesResult | null>
  /** 重新读取详情；keepDraft 为 false 时草稿换成新的生效定义。 */
  reload: (keepDraft?: boolean) => Promise<void>
  loadCases: () => Promise<void>
  flash: (msg: string) => void
  goTab: (tab: string) => void
}

export const SKILL_CTX: InjectionKey<SkillCtx> = Symbol('skill-ctx')

export function useSkillCtx(): SkillCtx {
  const c = inject(SKILL_CTX)
  if (!c) throw new Error('skill ctx missing')
  return c
}

/** 本页文案与常用显示函数。 */
export function useT() {
  const { t, locale } = useI18n()
  const T = (k: string, p?: Record<string, unknown>) => t(`ai-skills.${k}`, p ?? {})
  const L = (m: Record<string, string> | null | undefined) => pickLang(m, String(locale.value))
  const stLabel = (s: string) => T(`st.${['passed', 'corrected', 'rejected', 'unverifiable', 'error'].includes(s) ? s : 'unverifiable'}`)
  const vsCls = (s: string) => stCls(s)
  const usedBy = (u: string) => (['ask', 'generate', 'ingest', 'script_check', 'evolve', 'test', 'regression'].includes(u) ? T(`use.${u}`) : u)
  const vlabel = (v: string | null | undefined) => (!v || v === 'builtin' ? T('ver.builtin') : v === 'draft' || v === 'candidate' ? T(`ver.${v}`) : `v${v}`)
  return { t, T, L, locale, stLabel, vsCls, usedBy, vlabel }
}
