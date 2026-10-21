import { defineStore } from 'pinia'
import { ref } from 'vue'
import { notifications, type Notifications } from '@/views/join/join'

/**
 * 导航上的数字（M9-8，REQ-050）：等我审批的加入申请（我是属主或“管理”成员的项目），管理员另有创建权限的申请。
 * 外壳每次换页面时刷新，并每分钟刷新一次；审批后页面调用 refresh()。
 */
export const useNotify = defineStore('notify', () => {
  const data = ref<Notifications | null>(null)
  let inflight: Promise<void> | null = null

  async function refresh(): Promise<void> {
    if (inflight) return inflight
    inflight = (async () => {
      try { data.value = await notifications() } catch { /* 取不到时不显示数字 */ } finally { inflight = null }
    })()
    return inflight
  }
  function reset(): void { data.value = null }
  return { data, refresh, reset }
})
