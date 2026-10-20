<script setup lang="ts">
/**
 * “全部设备”时按网络的页面（拓扑、检查、脚本、成员、变更……）显示各网络汇总（M9 评审 allpages = summary；
 * 预览 DevelopDocs/ui-preview/M9/check.html、scripts.html 的“全部设备”状态）。数据来自 GET /projects/<项目>/networks
 * 的各网络 counts：检查页用 findings、脚本页用 scripts / scripts_with_errors、拓扑页用 annotations / ai_pending。
 * 升级前收藏的项目层旧网址也落到这里，点“进入”到那个网络的同一页面。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText } from '@/api'
import { useProject } from '@/stores/project'
import { useNetwork } from '@/stores/network'
import { basePage } from '@/project/scope'
import { colorClass, netName, sumKindOf, summaryRows, type NetRow } from './networks/logic'
import { shortTime } from './account/account'

const route = useRoute()
const project = useProject()
const network = useNetwork()
const { t } = useI18n()

const page = computed(() => basePage(route.name))
const kind = computed(() => sumKindOf(page.value))
const err = ref('')
const rows = computed(() => summaryRows(network.list))
const label = (n: NetRow) => netName(n, t('net.defaultName'))

async function load(): Promise<void> {
  if (!project.ref) return
  err.value = ''
  try { await network.load(project.ref, true) } catch (e) { err.value = errorText(e) }
}
onMounted(load)
watch(() => project.ref, load)
</script>

<template>
  <main class="main">
    <div class="page" data-testid="net-summary">
      <div class="crumbs"><span>{{ project.info?.name }}</span><span class="sep">/</span><span>{{ $t('net.all') }}</span><span class="sep">/</span><span>{{ $t(`nav.${page}`) }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t(`nav.${page}`) }}</h1>
          <p class="ph-sub">{{ $t('net.sumSub') }}</p>
        </div>
      </div>
      <div v-if="err" class="notice err" style="margin-bottom: 12px"><Icon name="err" /><div class="grow">{{ err }}</div></div>
      <section class="panel">
        <div class="panel-h"><h2>{{ $t(`net.sumTitle.${kind}`) }}</h2><span class="meta">{{ $t('net.sumPick') }}</span></div>
        <div class="nw-sum">
          <div class="nw-srow head">
            <span>{{ $t('net.colNetwork') }}</span><span>{{ $t('net.colDevices') }}</span>
            <span>{{ $t(`net.sumCol.${kind}`) }}</span>
            <span>{{ kind === 'findings' ? $t('net.colLastRun') : $t('net.colActivity') }}</span><span />
          </div>
          <div v-for="n in rows" :key="n.slug" :class="['nw-srow', colorClass(n.color)]" :data-testid="`sum-row-${n.slug}`">
            <span class="nn"><i class="nw-sq" />{{ label(n) }}<span v-if="n.default" class="nw-def">{{ $t('net.default') }}</span></span>
            <span>{{ n.counts.devices }}</span>
            <span v-if="kind === 'findings'" class="nw-cnt3">
              <span><i class="sevdot error" />{{ n.counts.findings.error }}</span>
              <span><i class="sevdot warning" />{{ n.counts.findings.warning }}</span>
              <span><i class="sevdot info" />{{ n.counts.findings.info }}</span>
              <span class="small faint">{{ $t('net.checkedOf', { n: n.counts.findings.devices_checked }) }}</span>
            </span>
            <span v-else-if="kind === 'scripts'">{{ $t('net.sumScripts', { n: n.counts.scripts, e: n.counts.scripts_with_errors }) }}</span>
            <span v-else-if="kind === 'topology'">{{ $t('net.sumTopo', { a: n.counts.annotations, p: n.counts.ai_pending }) }}</span>
            <span v-else-if="kind === 'members'">{{ n.default ? $t('net.includesAll') : $t('net.sumMembers', { s: n.counts.shared, p: n.counts.pinned }) }}</span>
            <span v-else>{{ $t('net.sumDevices', { p: n.counts.pinned }) }}</span>
            <span class="small muted">{{ kind === 'findings' ? (n.counts.findings.last_run ? shortTime(n.counts.findings.last_run) : '—') : (n.last_activity ? shortTime(n.last_activity.at) : '—') }}</span>
            <router-link class="btn btn-sm" :to="{ name: page, params: { ...route.params, network: n.slug }, query: route.query }" :data-testid="`sum-open-${n.slug}`">{{ $t('net.open') }}</router-link>
          </div>
        </div>
        <div v-if="kind === 'findings'" class="panel-f small muted"><Icon name="info" small /><span>{{ $t('net.sumFindingsNote') }}</span></div>
      </section>
    </div>
  </main>
</template>
