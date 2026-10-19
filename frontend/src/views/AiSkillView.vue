<script setup lang="ts">
/**
 * AI skill 详情（REQ-033，预览 DevelopDocs/ui-preview/REQ-033/skill.html、versions.html、evolve.html）：
 * 标签页 定义（编辑后保存为新版本）/ 试运行 / 统计与反馈 / 回归集与候选示例 / 版本历史 / 进化。仅管理员。
 * 未配置 AI 时查看、编辑、版本、回滚、统计照常；试运行只能回放；进化不可用。
 */
import { computed, provide, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import { errorText, get, put } from '@/api'
import Bits from './ai-skills/Bits.vue'
import DefPane from './ai-skills/DefPane.vue'
import TestPane from './ai-skills/TestPane.vue'
import StatsPane from './ai-skills/StatsPane.vue'
import CasesPane from './ai-skills/CasesPane.vue'
import VersionsPane from './ai-skills/VersionsPane.vue'
import EvolvePane from './ai-skills/EvolvePane.vue'
import { SKILL_CTX, useT } from './ai-skills/ctx'
import { cloneDef, evolveBlock, sameDef } from './ai-skills/logic'
import type { CasesResult, Definition, ListResult, SkillDetail } from './ai-skills/types'
import '@/styles/req033.css'

const TABS = ['def', 'test', 'stats', 'cases', 'versions', 'evolve'] as const
type Tab = (typeof TABS)[number]

const route = useRoute()
const router = useRouter()
const { T, L, usedBy } = useT()
const sid = computed(() => String(route.params.id ?? ''))
const tab = computed<Tab>(() => (TABS as readonly string[]).includes(String(route.query.tab)) ? (route.query.tab as Tab) : 'def')
const detail = ref<SkillDetail | null>(null)
const draft = ref<Definition | null>(null)
const cases = ref<CasesResult | null>(null)
const all = ref<{ id: string; title: Record<string, string> }[]>([])
const loading = ref(true)
const loadError = ref('')
const toast = ref('')
const offOpen = ref(false)
const dirty = computed(() => !!detail.value && !!draft.value && !sameDef(detail.value.definition, draft.value))

function flash(s: string): void {
  toast.value = s
  setTimeout(() => { if (toast.value === s) toast.value = '' }, 2600)
}
async function reload(keepDraft = false): Promise<void> {
  try {
    const d = await get<SkillDetail>(`/ai/skills/${sid.value}`)
    detail.value = d
    if (!keepDraft || !draft.value) draft.value = cloneDef(d.definition)
    loadError.value = ''
  } catch (e) { loadError.value = errorText(e) }
}
async function loadCases(): Promise<void> {
  try { cases.value = await get<CasesResult>(`/ai/skills/${sid.value}/cases`) } catch { cases.value = null }
}
async function loadAll(): Promise<void> {
  loading.value = true
  detail.value = null
  draft.value = null
  cases.value = null
  await Promise.all([reload(), loadCases()])
  loading.value = false
  if (!all.value.length) get<ListResult>('/ai/skills').then((r) => { all.value = r.skills.map((s) => ({ id: s.id, title: s.title })) }).catch(() => {})
}
watch(sid, (v) => { if (v) void loadAll() }, { immediate: true })

function goTab(t: string): void {
  void router.replace({ query: { ...route.query, tab: t === 'def' ? undefined : t } })
}
provide(SKILL_CTX, { sid, detail, draft, dirty, cases, reload, loadCases, flash, goTab })

onBeforeRouteLeave(() => (dirty.value ? window.confirm(T('def.leaveConfirm')) : true))
function switchSkill(e: Event): void {
  const id = (e.target as HTMLSelectElement).value
  if (dirty.value && !window.confirm(T('def.leaveConfirm'))) { (e.target as HTMLSelectElement).value = sid.value; return }
  draft.value = null
  void router.push({ name: 'ai-skill', params: { id }, query: route.query.tab ? { tab: route.query.tab } : {} })
}

const regN = computed(() => cases.value?.regression.length ?? detail.value?.stats.regression_cases ?? 0)
const evoWhy = computed(() => {
  const d = detail.value
  if (!d) return ''
  const k = evolveBlock({ configured: d.ai.configured, sid: d.id, enabled: d.enabled, regression: regN.value, pending: null, running: false })
  return k ? T(k) : ''
})

async function setEnabled(on: boolean): Promise<void> {
  const d = detail.value
  if (!d) return
  try {
    await put(`/ai/skills/${d.id}/enabled`, { enabled: on })
    d.enabled = on
    flash(T(on ? 'list.turnedOn' : 'list.turnedOff', { id: d.id }))
  } catch (e) { flash(errorText(e)) }
}
function onSwitch(e: Event): void {
  const el = e.target as HTMLInputElement
  if (!el.checked) { el.checked = true; offOpen.value = true } else void setEnabled(true)
}
function offText(id: string): string {
  return ['card-extract', 'ask-query', 'ask-answer', 'config-generate', 'script-review', 'skill-evolve'].includes(id) ? T(`off.${id}`) : T('off.other')
}
</script>

<template>
  <main class="main r33">
    <div class="page" data-testid="ai-skill">
      <div class="crumbs"><span>{{ $t('grp.sys') }}</span><span class="sep">/</span><router-link :to="{ name: 'ai-skills' }">{{ $t('nav.ai-skills') }}</router-link><span class="sep">/</span><span>{{ sid }}</span></div>
      <div v-if="loading" class="panel"><div class="empty">{{ $t('c.loading') }}</div></div>
      <div v-else-if="loadError && !detail" class="notice err" data-testid="sk-error"><Icon name="err" /><div class="grow">{{ loadError }}</div><button class="btn btn-sm" type="button" @click="loadAll">{{ $t('c.retry') }}</button></div>
      <template v-else-if="detail && draft">
        <div class="ph">
          <div class="ph-text">
            <div class="h1row"><h1 data-testid="sk-title">{{ L(detail.title) }}</h1><span class="sk-id">{{ detail.id }}</span><Bits kind="ver" :v="detail.active" cur data-testid="sk-active" /></div>
            <p class="ph-sub">{{ L(detail.description) }}</p>
            <div class="sk-meta">
              <span class="grp"><span class="k">{{ T('col.users') }}</span><span class="uchip">{{ usedBy(detail.used_by) }}</span></span>
              <span class="grp"><span class="k">{{ T('col.model') }}</span><span class="model"><span class="mk">{{ detail.task }} → {{ detail.model_key || T('model.default') }}</span><span class="mn" :class="{ dflt: !detail.model }">{{ detail.model || T('model.unset') }}</span></span></span>
              <label class="grp check"><span class="switch"><input type="checkbox" :checked="detail.enabled" data-testid="sk-enabled" @change="onSwitch"><span /></span><span>{{ T(detail.enabled ? 'on' : 'off') }}</span></label>
            </div>
          </div>
          <div class="ph-actions">
            <select class="select skill-sel" :value="sid" :aria-label="T('detail.switch')" data-testid="sk-select" @change="switchSkill">
              <option v-for="s in all" :key="s.id" :value="s.id">{{ L(s.title) }}（{{ s.id }}）</option>
            </select>
            <button class="btn" type="button" data-testid="sk-go-versions" @click="goTab('versions')"><Icon name="history" small />{{ T('tab.versions') }}</button>
            <span class="evo-wrap">
              <button class="btn" type="button" :disabled="!!evoWhy" :title="evoWhy" data-testid="sk-go-evolve" @click="goTab('evolve')"><Icon name="dna" small />{{ T('detail.evolve') }}</button>
              <span class="evo-why" data-testid="sk-evo-why">{{ evoWhy }}</span>
            </span>
          </div>
        </div>
        <div v-if="!detail.ai.configured" class="notice warn" style="margin-bottom: 14px" data-testid="sk-ai-off">
          <Icon name="info" />
          <div class="grow"><b>{{ T('aiOff.title') }}</b>{{ T('aiOff.detail') }}</div>
          <router-link class="btn btn-sm" :to="{ name: 'ai-settings' }"><Icon name="plug" small />{{ T('aiOff.setup') }}</router-link>
        </div>
        <div class="tabs" role="tablist" data-testid="sk-tabs">
          <button v-for="t in TABS" :key="t" type="button" role="tab" :aria-selected="tab === t" :data-testid="`sk-tab-${t}`" @click="goTab(t)">
            {{ T(`tab.${t}`) }}
            <span v-if="t === 'def' && dirty" class="count" style="color: var(--amber-ink)">●</span>
            <span v-if="t === 'cases'" class="count">{{ regN }}</span>
            <span v-if="t === 'evolve' && detail.stats.pending_evolutions" class="count" style="color: var(--r33-ai-ink)">{{ detail.stats.pending_evolutions }}</span>
          </button>
        </div>
        <DefPane v-show="tab === 'def'" />
        <TestPane v-if="tab === 'test'" />
        <StatsPane v-if="tab === 'stats'" />
        <CasesPane v-if="tab === 'cases'" />
        <VersionsPane v-if="tab === 'versions'" />
        <EvolvePane v-if="tab === 'evolve'" />
      </template>
    </div>

    <div v-if="offOpen && detail" class="modal-back" @click.self="offOpen = false">
      <div class="modal" role="dialog" aria-modal="true" style="width: min(520px, 100%)" data-testid="sk-off-dialog">
        <div class="modal-h"><h2>{{ T('off.title') }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="offOpen = false"><Icon name="x" /></button></div>
        <div class="modal-b"><p>{{ offText(detail.id) }}</p></div>
        <div class="modal-f"><button class="btn" type="button" @click="offOpen = false">{{ $t('c.cancel') }}</button><button class="btn btn-danger" type="button" data-testid="sk-off-ok" @click="offOpen = false; setEnabled(false)">{{ T('off.ok') }}</button></div>
      </div>
    </div>
    <div v-if="toast" class="toast" role="status" data-testid="sk-toast">{{ toast }}</div>
  </main>
</template>
