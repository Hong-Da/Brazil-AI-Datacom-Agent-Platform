<script setup lang="ts">
/**
 * 网络概览（M9，/p/<项目>/n/<网络>；预览 DevelopDocs/ui-preview/M9/switcher.html）：本网络的设备、检查问题、脚本、
 * 固定版本、待处理的 AI 建议（各自链到对应页面），网址与网络的对应，以及本项目的其他网络卡片。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import NetChip from '@/components/net-chip.vue'
import { errorText } from '@/api'
import { useProject } from '@/stores/project'
import { useNetwork } from '@/stores/network'
import { colorClass, netActivityKey, netName, netOrder, type NetRow } from './networks/logic'
import { shortTime } from './account/account'

const route = useRoute()
const project = useProject()
const network = useNetwork()
const { t } = useI18n()
const err = ref('')

const n = computed(() => network.info)
const label = (x: NetRow) => netName(x, t('net.defaultName'))
const others = computed(() => netOrder(network.list))
const f = computed(() => n.value?.counts.findings)
const PAGES = ['topology', 'check', 'scripts', 'members', 'devices', 'networks'] as const
function pathOf(p: string): string {
  const base = `/p/${project.ref ?? ''}`
  return p === 'networks' ? `${base}/networks` : `${base}/n/${n.value?.slug ?? ''}/${p}`
}
function actText(a: NetRow['last_activity']): string {
  if (!a) return '—'
  const k = netActivityKey(a.action)
  return k ? t(`net.act.${k}`) : a.action
}

async function load(): Promise<void> {
  if (!project.ref) return
  err.value = ''
  try { await network.load(project.ref, true) } catch (e) { err.value = errorText(e) }
}
onMounted(load)
watch(() => route.params.network, load)
</script>

<template>
  <main class="main">
    <div class="page" data-testid="network-home">
      <div class="crumbs"><span>{{ project.info?.name }}</span><span class="sep">/</span><NetChip v-if="n" :net="n" /></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.network-home') }}</h1>
          <p class="ph-sub">{{ $t('net.homeSub') }}</p>
        </div>
        <div class="ph-actions"><router-link class="btn" :to="{ name: 'networks', params: { project: project.ref } }"><Icon name="network" small />{{ $t('net.manage') }}</router-link></div>
      </div>
      <div v-if="err" class="notice err" style="margin-bottom: 12px"><Icon name="err" /><div class="grow">{{ err }}</div></div>
      <template v-if="n">
        <div class="nw-kpis" data-testid="net-kpis">
          <router-link :to="{ name: 'members' }"><b>{{ n.counts.devices }}</b><span>{{ $t('net.k.devices') }}</span><small>{{ n.default ? $t('net.includesAll') : $t('net.k.shared', { n: n.counts.shared }) }}</small></router-link>
          <router-link :to="{ name: 'check' }"><b>{{ (f?.error ?? 0) + (f?.warning ?? 0) + (f?.info ?? 0) }}</b><span>{{ $t('net.k.findings') }}</span><small>{{ $t('net.k.findingsSub', { e: f?.error ?? 0, w: f?.warning ?? 0 }) }}</small></router-link>
          <router-link :to="{ name: 'scripts' }"><b>{{ n.counts.scripts }}</b><span>{{ $t('net.k.scripts') }}</span><small>{{ $t('net.k.scriptsSub', { n: n.counts.scripts_with_errors }) }}</small></router-link>
          <router-link :to="{ name: 'members' }"><b>{{ n.counts.pinned }}</b><span>{{ $t('net.k.pinned') }}</span><small>{{ $t('net.k.pinnedSub') }}</small></router-link>
          <router-link :to="{ name: 'topology' }"><b>{{ n.counts.ai_pending }}</b><span>{{ $t('net.k.ai') }}</span><small>{{ $t('net.k.aiSub', { n: n.counts.annotations }) }}</small></router-link>
        </div>
        <div class="nw-notes mt16">
          <section class="panel">
            <div class="panel-h"><h2>{{ $t('net.urlTitle') }}</h2><span class="meta">{{ $t('net.urlMeta') }}</span></div>
            <table class="tbl">
              <thead><tr><th>{{ $t('net.colPage') }}</th><th>{{ $t('net.colUrl') }}</th></tr></thead>
              <tbody>
                <tr v-for="p in PAGES" :key="p"><td class="nowrap">{{ $t(`nav.${p}`) }}</td><td><code class="small">{{ pathOf(p) }}</code> <span v-if="p === 'networks'" class="tag">{{ $t('net.projectLevel') }}</span></td></tr>
              </tbody>
            </table>
            <div class="panel-f small muted"><Icon name="info" small /><span>{{ $t('net.urlNote') }}</span></div>
          </section>
          <section class="panel">
            <div class="panel-h"><h2>{{ $t('net.aboutTitle') }}</h2></div>
            <div class="panel-b" style="display: flex; flex-direction: column; gap: 8px; font-size: 12.5px">
              <div><span class="faint">{{ $t('net.colActivity') }}：</span>{{ actText(n.last_activity) }} <span class="faint">{{ n.last_activity?.actor ?? '' }} · {{ shortTime(n.last_activity?.at ?? null) }}</span></div>
              <div v-if="n.copied_from"><span class="faint">{{ $t('net.copiedFrom') }}：</span>{{ n.copied_from.name }} <span class="faint">{{ shortTime(n.copied_from.at) }}</span></div>
              <div v-if="n.description">{{ n.description }}</div>
              <div><span class="faint">{{ $t('net.colRules') }}：</span>{{ n.default ? $t('net.allNew') : $t('net.nRules', { n: n.counts.rules }) }}</div>
              <div><span class="faint">{{ $t('net.workData') }}：</span>{{ $t('net.workDataText', { a: n.counts.annotations, i: n.counts.ignores, o: n.counts.overrides }) }}</div>
            </div>
          </section>
        </div>
        <div class="section-t" style="margin-top: 18px">{{ $t('net.inProject') }}</div>
        <div class="nw-cards">
          <router-link v-for="x in others" :key="x.slug" :class="['nw-card', colorClass(x.color), { 'is-cur': x.slug === n.slug }]" :to="{ name: 'network-home', params: { network: x.slug } }" :data-testid="`net-card-${x.slug}`">
            <span class="t"><i class="nw-sq" />{{ label(x) }}<span v-if="x.default" class="nw-def">{{ $t('net.default') }}</span></span>
            <span class="m">{{ $t('net.cardMeta', { d: x.counts.devices, f: x.counts.findings.error + x.counts.findings.warning + x.counts.findings.info, s: x.counts.scripts }) }}</span>
            <span class="f">{{ x.folder ? `${$t('net.folder')} ${x.folder} · ` : '' }}{{ shortTime(x.last_activity?.at ?? x.created_at) }}</span>
          </router-link>
        </div>
      </template>
    </div>
  </main>
</template>
