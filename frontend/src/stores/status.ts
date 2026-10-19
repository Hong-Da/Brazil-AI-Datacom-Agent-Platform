import { defineStore } from 'pinia'
import { ref } from 'vue'
import { get } from '@/api'

/** 首页概况（/summary）的精简版：外壳上的知识库版本、草稿数、审核与未识别行计数、AI 状态。各页面修改知识库后调用 refresh()。 */
export interface Summary {
  kb: { version: string; released: string | null; draft_changes: number; profiles: number; avg_coverage: number; unfilled_profiles: number; cards: number; nodes: number }
  review: { pending: number; by_kind: Record<string, number> }
  unknown: { patterns: number; total: number }
  devices: { count: number; stale: number; roundtrip_failed: number; recent: unknown[] }
  regression: unknown | null
  ai: { configured: boolean; reason?: string | null } // reason：按当前账号没有可用 AI 的原因（REQ-040）
}

export const useStatus = defineStore('status', () => {
  const summary = ref<Summary | null>(null)
  const appVersion = ref('')
  let inflight: Promise<void> | null = null

  async function refresh(): Promise<void> {
    if (inflight) return inflight
    inflight = (async () => {
      try {
        summary.value = await get<Summary>('/summary')
        if (!appVersion.value) appVersion.value = (await get<{ version: string }>('/health')).version
      } catch { /* 外壳计数取不到时不影响页面 */ } finally { inflight = null }
    })()
    return inflight
  }
  return { summary, appVersion, refresh }
})
