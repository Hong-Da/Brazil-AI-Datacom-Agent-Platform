/** 设备图标需要的项目数据：视图标注（角色、分组……、采纳的推测对端）与待采纳的拓扑整理建议（REQ-042 / M8-3）。 */
import { get, put } from '@/api'
import { projectPath, query } from '@/components/ai-suggest/logic'
import type { Annotation, PendingSuggestion } from './logic'

export interface TopoMarks { annotations: Annotation[]; pending: PendingSuggestion[] }

/** 读取项目的视图标注与待采纳的 topology-roles 建议；读取失败时返回空（图标退回平台默认，不影响页面）。 */
export async function loadMarks(project: string): Promise<TopoMarks> {
  const P = (p: string) => projectPath(project, p)
  const [a, s] = await Promise.all([
    get<{ items: Annotation[] }>(P('/view-annotations')).catch(() => ({ items: [] as Annotation[] })),
    get<{ items: PendingSuggestion[] }>(P(`/ai/suggestions${query({ skill: 'topology-roles', scope: 'topology', status: 'pending', limit: 500 })}`))
      .catch(() => ({ items: [] as PendingSuggestion[] })),
  ])
  return { annotations: a.items ?? [], pending: s.items ?? [] }
}

/** 手工标注（来源 user，优先于 AI）；value 为 null 时删除。 */
export async function saveAnnotation(project: string, deviceId: number, key: 'role' | 'group' | 'layer' | 'label', value: string | number | null): Promise<Annotation | null> {
  const r = await put<{ item: Annotation | null }>(projectPath(project, '/view-annotations'), { target_type: 'device', target: String(deviceId), key, value })
  return r?.item ?? null
}
