/** 单台设备的图标（设备配置图、设备配置分析页用）：按项目视图标注取角色，叠加配置过期与 AI 待采纳角标。 */
import { computed, ref, watch, type Ref } from 'vue'
import { useProject } from '@/stores/project'
import { loadMarks } from './data'
import { annoByDevice, badgesOf, pendingOf, resolveRole, vendorCode, type Annotation, type PendingSuggestion, type Resolved } from './logic'
import type { Badge, VendorCode } from './lmi'

export interface DevLike { id: number; name: string; vendor?: string | null; profile?: string | null; stale?: boolean }
export interface DevIcon { glyph: string; vendor: VendorCode | ''; badges: Badge[]; resolved: Resolved }

export function useDeviceIcon(dev: Ref<DevLike | null | undefined>): { icon: Ref<DevIcon | null>; reload: () => Promise<void> } {
  const project = useProject()
  const annos = ref<Annotation[]>([])
  const pending = ref<PendingSuggestion[]>([])
  async function reload(): Promise<void> {
    if (!project.ref) return
    const m = await loadMarks(project.ref)
    annos.value = m.annotations
    pending.value = m.pending
  }
  watch(() => project.ref, () => void reload(), { immediate: true })
  const icon = computed<DevIcon | null>(() => {
    const d = dev.value
    if (!d) return null
    const resolved = resolveRole(annoByDevice(annos.value).get(String(d.id)), d.profile, d.vendor)
    const ai = pendingOf(pending.value).hints.some((h) => h.device_id === d.id)
    return { glyph: resolved.glyph, vendor: vendorCode(d.vendor, d.profile), badges: badgesOf({ stale: !!d.stale, ai }), resolved }
  })
  return { icon, reload }
}
