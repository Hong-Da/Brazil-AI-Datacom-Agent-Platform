/** 报告导出（POST /api/v1/reports）与目标（设备 / 粘贴的配置）的共享状态。 */
import { reactive } from 'vue'
import { ApiError, apiUrl } from '@/api'
import { i18n } from '@/i18n'

export type ReportLang = 'zh-CN' | 'en'
export type ReportFormat = 'html' | 'md'

/** 检查页与清理页共用的目标：在两个页面之间切换时保留（粘贴的文本只在本次会话的内存里）。 */
export const target = reactive({
  mode: 'device' as 'device' | 'text',
  deviceId: null as number | null,
  text: '',
  /** 最近一次检查的计数，供清理页的标签显示 */
  findings: null as number | null,
  rulesOn: null as number | null,
  rulesAll: null as number | null,
  orphans: null as number | null,
})

export type TargetBody = { device_id: number } | { text: string }

export function targetBody(): TargetBody | null {
  if (target.mode === 'device') return target.deviceId != null ? { device_id: target.deviceId } : null
  return target.text.trim() ? { text: target.text } : null
}

/** 从 Content-Disposition 取文件名（支持 filename*=UTF-8''…）。 */
export function dispositionName(h: string | null, fallback: string): string {
  if (!h) return fallback
  const star = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(h)
  if (star) {
    try { return decodeURIComponent(star[1].trim()) } catch { /* 用普通文件名 */ }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/.exec(h)
  return plain ? plain[1].trim() : fallback
}

export const reportName = (kind: string, device: string | null, lang: ReportLang, fmt: ReportFormat): string =>
  `${kind}-${(device || 'config').replace(/[^\w.-]+/g, '_')}.${lang}.${fmt}`

/** POST 后拿文件：成功时返回 blob 与文件名；失败时按 {code, message} 抛 ApiError。 */
export async function postFile(path: string, body: unknown, fallback: string): Promise<{ blob: Blob; name: string }> {
  const res = await fetch(apiUrl(path), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept-Language': String(i18n.global.locale.value),
    },
    body: JSON.stringify(body),
  })
  const type = res.headers.get('Content-Type') ?? ''
  if (!res.ok || type.includes('application/json')) {
    let msg = res.statusText
    let code = 1000
    let data: unknown = null
    try {
      const j = await res.json()
      if (j && typeof j === 'object' && 'code' in j) {
        code = j.code
        msg = j.message || msg
        data = j.data
      }
    } catch { /* 不是 JSON */ }
    throw new ApiError(code, msg || String(res.status), res.status, data)
  }
  return { blob: await res.blob(), name: dispositionName(res.headers.get('Content-Disposition'), fallback) }
}

export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  setTimeout(() => { URL.revokeObjectURL(url); a.remove() }, 500)
}
