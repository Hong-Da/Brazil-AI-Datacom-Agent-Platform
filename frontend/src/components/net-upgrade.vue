<script setup lang="ts">
/**
 * 升级说明：项目里有了网络（M9，预览 DevelopDocs/ui-preview/M9/upgrade.html）。升级时每个项目建了默认网络（包含全部设备，
 * 原来的工作数据都移了进去）。项目还只有默认网络时，在设备页与网络页顶部显示一次（按账号与项目记在浏览器里，点“知道了”后不再显示）；
 * 网络页的“说明”按钮可以再打开（force）。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { useAuth } from '@/stores/auth'
import { useProject } from '@/stores/project'
import { useNetwork } from '@/stores/network'
import { netName } from '@/views/networks/logic'

const props = defineProps<{ force?: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const auth = useAuth()
const project = useProject()
const network = useNetwork()
const { t } = useI18n()

const key = computed(() => `lmesh-net-upgrade:${auth.me?.username ?? ''}:${project.ref ?? ''}`)
const seen = ref(false)
function readSeen(): boolean {
  try { return localStorage.getItem(key.value) === '1' } catch { return false }
}
const def = computed(() => network.defaultNet)
const show = computed(() => {
  void key.value
  if (props.force) return !!def.value
  return !!def.value && network.networks.length === 1 && !seen.value && !readSeen()
})
function ok(): void {
  try { localStorage.setItem(key.value, '1') } catch { /* 忽略 */ }
  seen.value = true
  emit('close')
}
</script>

<template>
  <article v-if="show && def" class="panel nw-upg" data-testid="net-upgrade">
    <div class="nw-upg-h">
      <span class="nw-upg-ic nc-slate"><Icon name="network" /></span>
      <div>
        <h2>{{ $t('net.u.title') }}</h2>
        <p>{{ $t('net.u.lead', { n: netName(def, t('net.defaultName')) }) }}</p>
      </div>
    </div>
    <div class="nw-upg-b">
      <div>
        <b>{{ $t('net.u.moved') }}</b>
        <div class="nw-dlist" style="margin-top: 6px">
          <span>{{ $t('net.cw.members') }}</span><b>{{ def.counts.devices }}</b>
          <span>{{ $t('net.cw.annotations') }}</span><b>{{ def.counts.annotations }}</b>
          <span>{{ $t('net.dw.checks') }}</span><b>{{ $t('net.dw.checksN', { i: def.counts.ignores, o: def.counts.overrides }) }}</b>
          <span>{{ $t('net.cw.scripts') }}</span><b>{{ def.counts.scripts }}</b>
          <span>{{ $t('net.u.ai') }}</span><b>{{ def.counts.ai_pending }}</b>
        </div>
      </div>
      <div>
        <b>{{ $t('net.u.stay') }}</b>
        <ul><li>{{ $t('net.lp1') }}</li><li>{{ $t('net.lp2') }}</li><li>{{ $t('net.lp3') }}</li></ul>
        <b>{{ $t('net.u.urls') }}</b>
        <ul><li>{{ $t('net.u.url1', { p: project.ref ?? '', n: def.slug }) }}</li><li>{{ $t('net.u.url2') }}</li><li>{{ $t('net.u.url3') }}</li></ul>
      </div>
    </div>
    <div class="nw-upg-f">
      <router-link class="btn btn-primary btn-sm" :to="{ name: 'network-suggest', params: { project: project.ref } }"><Icon name="wand" small />{{ $t('net.u.toSugg') }}</router-link>
      <router-link class="btn btn-sm" :to="{ name: 'network-home', params: { project: project.ref, network: def.slug } }"><Icon name="network" small />{{ $t('net.u.toDefault') }}</router-link>
      <span style="flex: 1" />
      <button class="btn btn-ghost btn-sm" type="button" data-testid="net-upgrade-ok" @click="ok">{{ $t('net.u.ok') }}</button>
    </div>
  </article>
</template>

<style scoped>
.nw-upg { margin-bottom: 14px; overflow: hidden; }
.nw-upg-h { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 14px; align-items: center; padding: 14px 16px; border-bottom: 1px solid var(--line); background: color-mix(in srgb, var(--n-slate) 6%, var(--surface)); }
.nw-upg-h h2 { font-size: 15px; margin: 0; }
.nw-upg-h p { color: var(--ink-2); margin: 4px 0 0; max-width: 80ch; font-size: 12.5px; }
.nw-upg-ic { width: 36px; height: 36px; border-radius: 8px; display: inline-flex; align-items: center; justify-content: center; color: var(--nci); background: color-mix(in srgb, var(--nc) 14%, var(--surface)); border: 1px solid color-mix(in srgb, var(--nc) 40%, transparent); }
.nw-upg-b { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr); gap: 16px; padding: 12px 16px; font-size: 12.5px; }
.nw-upg-b ul { margin: 4px 0 8px; padding-left: 18px; color: var(--ink-2); display: flex; flex-direction: column; gap: 3px; }
.nw-upg-f { display: flex; gap: 8px; align-items: center; padding: 10px 16px; border-top: 1px solid var(--line); background: var(--surface-2); flex-wrap: wrap; }
@media (max-width: 900px) { .nw-upg-b { grid-template-columns: 1fr; } }
</style>
