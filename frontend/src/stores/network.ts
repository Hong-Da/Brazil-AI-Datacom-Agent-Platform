import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { get, setApiNetwork } from '@/api'
import type { NetList, NetRow } from '@/views/networks/logic'

/**
 * 当前网络（M9，REQ-045）：网址 /p/<项目>/n/<网络>/… 决定；项目层网址（“全部设备”）为 null。
 * 列表（GET /projects/<项目>/networks：网络、文件夹、颜色组、项目概览与各网络汇总）按项目缓存，切换器、导航、汇总页共用。
 * 接口改写（api.ts）只跟网址走：路由守卫在按网络的页面设置 apiNetwork，其他页面清掉；cur 留给导航链接沿用。
 */
export const useNetwork = defineStore('network', () => {
  /** 当前网络的标识（null = 全部设备） */
  const cur = ref<string | null>(null)
  /** 列表属于哪个项目 */
  const project = ref<string | null>(null)
  const list = ref<NetList | null>(null)
  let pending: Promise<NetList> | null = null

  const networks = computed<NetRow[]>(() => list.value?.networks ?? [])
  const info = computed<NetRow | null>(() => networks.value.find((n) => n.slug === cur.value) ?? null)
  const defaultNet = computed<NetRow | null>(() => networks.value.find((n) => n.default) ?? null)

  /** 读当前项目的网络列表（force 时重读）；同一项目只读一次，写操作后由调用方 force。 */
  async function load(ref_: string, force = false): Promise<NetList> {
    if (!force && project.value === ref_ && list.value) return list.value
    if (!force && pending && project.value === ref_) return pending
    if (project.value !== ref_) {
      // 换了项目：上一个项目的网络不再有效
      cur.value = null
      list.value = null
    }
    project.value = ref_
    const p = get<NetList>(`/projects/${encodeURIComponent(ref_)}/networks`)
    pending = p
    try {
      const data = await p
      if (project.value === ref_) list.value = data
      return data
    } finally {
      if (pending === p) pending = null
    }
  }

  /** 网址里的网络（或 null）：设为当前，并让接口改走它。 */
  function enter(slug: string | null): void {
    cur.value = slug
    setApiNetwork(slug)
  }

  /** 离开按网络的页面（项目层或非项目页面）：接口回到项目层，cur 保留给导航。 */
  function leave(): void {
    setApiNetwork(null)
  }

  /** 换了项目：清掉当前网络与列表。 */
  function reset(): void {
    cur.value = null
    project.value = null
    list.value = null
    setApiNetwork(null)
  }

  return { cur, project, list, networks, info, defaultNet, load, enter, leave, reset }
})
