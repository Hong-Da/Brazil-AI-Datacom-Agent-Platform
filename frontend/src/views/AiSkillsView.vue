<script setup lang="ts">
/**
 * AI skill 列表（REQ-033，预览 DevelopDocs/ui-preview/REQ-033/skills.html）：每个调用 AI 的地方一个 skill，
 * 显示启用、当前版本、近 30 天调用、代码校验通过率、被拦截比例、评价与回归集；停用前确认影响。仅管理员。
 */
import { computed, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { errorText, get, put } from '@/api'
import Bits from './ai-skills/Bits.vue'
import { useT } from './ai-skills/ctx'
import { pct, pctOf, sumCounts } from './ai-skills/logic'
import type { ListResult, SkillInfo } from './ai-skills/types'
import '@/styles/req033.css'

const { T, L, usedBy } = useT()
const data = ref<ListResult | null>(null)
const loading = ref(true)
const loadError = ref('')
const q = ref('')
const use = ref('')
const pending = ref<SkillInfo | null>(null)
const busy = ref('')
const toast = ref('')

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try { data.value = await get<ListResult>('/ai/skills?days=30') } catch (e) { loadError.value = errorText(e) } finally { loading.value = false }
}
onMounted(load)

function flash(s: string): void {
  toast.value = s
  setTimeout(() => { if (toast.value === s) toast.value = '' }, 2400)
}

const skills = computed(() => data.value?.skills ?? [])
const users = computed(() => [...new Set(skills.value.map((s) => s.used_by))])
const shown = computed(() => skills.value.filter((s) => {
  if (use.value && s.used_by !== use.value) return false
  const k = q.value.trim().toLowerCase()
  return !k || `${L(s.title)} ${s.id}`.toLowerCase().includes(k)
}))
const tot = computed(() => sumCounts(skills.value.map((s) => s.stats)))
const onN = computed(() => skills.value.filter((s) => s.enabled).length)
const evo = computed(() => skills.value.filter((s) => s.stats.pending_evolutions > 0))
const evoN = computed(() => evo.value.reduce((n, s) => n + s.stats.pending_evolutions, 0))

async function setEnabled(s: SkillInfo, on: boolean): Promise<void> {
  busy.value = s.id
  try {
    await put(`/ai/skills/${s.id}/enabled`, { enabled: on })
    s.enabled = on
    flash(T(on ? 'list.turnedOn' : 'list.turnedOff', { id: s.id }))
  } catch (e) { flash(errorText(e)) } finally { busy.value = '' }
}
function onSwitch(s: SkillInfo, e: Event): void {
  const el = e.target as HTMLInputElement
  if (!el.checked) {
    el.checked = true
    pending.value = s
  } else void setEnabled(s, true)
}
async function confirmOff(): Promise<void> {
  const s = pending.value
  pending.value = null
  if (s) await setEnabled(s, false)
}
function offText(id: string): string {
  return ['card-extract', 'ask-query', 'ask-answer', 'config-generate', 'script-review', 'skill-evolve'].includes(id) ? T(`off.${id}`) : T('off.other')
}
</script>

<template>
  <main class="main r33">
    <div class="page" data-testid="ai-skills">
      <div class="crumbs"><span>{{ $t('grp.sys') }}</span><span class="sep">/</span><span>{{ $t('nav.ai-skills') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ T('title') }}</h1>
          <p class="ph-sub">{{ T('sub') }}</p>
        </div>
        <div class="ph-actions"><button class="btn" type="button" data-testid="sk-refresh" @click="load"><Icon name="refresh" small />{{ $t('c.refresh') }}</button></div>
      </div>

      <div v-if="loading && !data" class="panel"><div class="empty">{{ $t('c.loading') }}</div></div>
      <div v-else-if="loadError" class="notice err" data-testid="sk-error"><Icon name="err" /><div class="grow">{{ loadError }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
      <template v-else-if="data">
        <div v-if="!data.ai.configured" class="notice warn" style="margin-bottom: 14px" data-testid="sk-ai-off">
          <Icon name="info" />
          <div class="grow"><b>{{ T('aiOff.title') }}</b>{{ T('aiOff.list') }}</div>
          <router-link class="btn btn-sm" :to="{ name: 'ai-settings' }"><Icon name="plug" small />{{ T('aiOff.setup') }}</router-link>
        </div>

        <div class="strip sk-strip" data-testid="sk-kpi">
          <div><div class="k">{{ T('kpi.skills') }}</div><div class="v">{{ skills.length }}</div><div class="s">{{ T('kpi.onOff', { on: onN, off: skills.length - onN }) }}</div></div>
          <div><div class="k">{{ T('kpi.calls', { d: data.days }) }}</div><div class="v">{{ tot.calls.toLocaleString() }}</div><div class="s">{{ T('kpi.callsNote') }}</div></div>
          <div>
            <div class="k">{{ T('kpi.rate') }}</div><div class="v">{{ pctOf(tot.passed, tot.calls) }}</div>
            <div class="s"><Bits v-if="tot.calls" kind="stack" :counts="tot" /><template v-else>{{ T('kpi.noCalls') }}</template></div>
          </div>
          <div>
            <div class="k">{{ T('kpi.evo') }}</div><div class="v" :style="evoN ? { color: 'var(--r33-ai-ink)' } : undefined">{{ evoN }}</div>
            <div class="s">
              <router-link v-if="evo.length" :to="{ name: 'ai-skill', params: { id: evo[0].id }, query: { tab: 'evolve' } }">{{ T('kpi.evoGo', { id: evo[0].id }) }}</router-link>
              <template v-else>{{ T('kpi.evoNone') }}</template>
            </div>
          </div>
        </div>

        <section class="panel">
          <div class="panel-h toolbar" style="padding: 8px 12px">
            <label class="input-wrap" style="width: 240px"><Icon name="search" small /><input v-model="q" class="input" type="search" :placeholder="T('list.filter')" data-testid="sk-filter"></label>
            <select v-model="use" class="select" style="width: auto" data-testid="sk-use">
              <option value="">{{ T('list.allUsers') }}</option>
              <option v-for="u in users" :key="u" :value="u">{{ usedBy(u) }}</option>
            </select>
            <span class="grow" />
            <Bits kind="legend" />
          </div>
          <div class="tbl-wrap">
            <table class="tbl sk-tbl" data-testid="sk-table">
              <thead><tr>
                <th>{{ T('col.skill') }}</th><th>{{ T('col.users') }}</th><th>{{ T('col.model') }}</th><th>{{ T('col.on') }}</th><th>{{ T('col.ver') }}</th>
                <th class="num">{{ T('col.calls') }}</th><th>{{ T('col.rate') }}</th><th class="num">{{ T('col.blocked') }}</th><th>{{ T('col.feedback') }}</th><th class="num">{{ T('col.reg') }}</th><th />
              </tr></thead>
              <tbody>
                <tr v-for="s in shown" :key="s.id" :class="{ 'is-off': !s.enabled }" :data-skill="s.id" data-testid="sk-row">
                  <td class="sk-name">
                    <div class="h"><router-link :to="{ name: 'ai-skill', params: { id: s.id } }" data-testid="sk-open-name">{{ L(s.title) }}</router-link><span class="sk-id">{{ s.id }}</span></div>
                    <div class="d">{{ L(s.description) }}</div>
                  </td>
                  <td><div class="users"><span class="uchip">{{ usedBy(s.used_by) }}</span></div></td>
                  <td><div class="model"><span class="mk">{{ s.task }} → {{ s.model_key || T('model.default') }}</span><span class="mn" :class="{ dflt: !s.model }">{{ s.model || T('model.unset') }}</span></div></td>
                  <td class="keep">
                    <label class="switch" :title="T(s.enabled ? 'on' : 'off')"><input type="checkbox" :checked="s.enabled" :disabled="busy === s.id" :data-testid="`sk-switch-${s.id}`" @change="onSwitch(s, $event)"><span /></label>
                  </td>
                  <td class="keep"><Bits kind="ver" :v="s.active" /></td>
                  <td class="num"><template v-if="s.stats.calls">{{ s.stats.calls }}</template><span v-else class="faint">0</span></td>
                  <td><Bits v-if="s.stats.calls" kind="rate" :r="s.stats.pass_rate" /><span v-else class="faint small">{{ T('list.noCalls') }}</span></td>
                  <td class="num"><span class="blk" :class="{ hi: (s.stats.reject_rate ?? 0) > 0.15 }">{{ s.stats.calls ? pct(s.stats.reject_rate) : '—' }}</span></td>
                  <td><Bits kind="rates" :counts="s.stats" /></td>
                  <td class="num">
                    <span v-if="s.id === 'skill-evolve'" class="faint small" :title="T('list.metaNoReg')">—</span>
                    <span v-else class="regn">{{ s.stats.regression_cases }}<small v-if="s.stats.candidates">{{ T('list.cand', { n: s.stats.candidates }) }}</small></span>
                  </td>
                  <td class="right keep nowrap">
                    <router-link v-if="s.stats.pending_evolutions" class="evobadge" :to="{ name: 'ai-skill', params: { id: s.id }, query: { tab: 'evolve' } }" :title="T('list.evoTip')"><Icon name="dna" small />{{ T('list.evoPending', { n: s.stats.pending_evolutions }) }}</router-link>
                    {{ ' ' }}<router-link class="btn btn-sm" :to="{ name: 'ai-skill', params: { id: s.id } }" :data-testid="`sk-open-${s.id}`">{{ T('list.open') }}</router-link>
                  </td>
                </tr>
                <tr v-if="!shown.length"><td colspan="11" class="muted" style="text-align: center; padding: 24px">{{ T('list.none') }}</td></tr>
              </tbody>
            </table>
          </div>
          <div class="panel-f small faint">{{ T('list.foot') }}</div>
        </section>
      </template>
    </div>

    <div v-if="pending" class="modal-back" @click.self="pending = null">
      <div class="modal" role="dialog" aria-modal="true" style="width: min(520px, 100%)" data-testid="sk-off-dialog">
        <div class="modal-h"><h2>{{ T('off.title') }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="pending = null"><Icon name="x" /></button></div>
        <div class="modal-b"><p>{{ offText(pending.id) }}</p></div>
        <div class="modal-f"><button class="btn" type="button" @click="pending = null">{{ $t('c.cancel') }}</button><button class="btn btn-danger" type="button" data-testid="sk-off-ok" @click="confirmOff">{{ T('off.ok') }}</button></div>
      </div>
    </div>
    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </main>
</template>
