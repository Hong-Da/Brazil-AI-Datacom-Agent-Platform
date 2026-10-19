<script setup lang="ts">
/**
 * AI skill 列表（REQ-033，预览 DevelopDocs/ui-preview/REQ-033/skills.html）：每个调用 AI 的地方一个 skill，
 * 显示启用、当前版本、近 30 天调用、代码校验通过率、被拦截比例、评价与回归集；停用前确认影响。仅管理员。
 * 按功能分组（REQ-033 评审修改）：组可折叠、标题带个数、可按组筛选；搜索跨组匹配编号、名称、说明，只显示有匹配的组。
 */
import { computed, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import AiOffHint from '@/components/ai-off-hint.vue'
import { errorText, get, put } from '@/api'
import Bits from './ai-skills/Bits.vue'
import { useT } from './ai-skills/ctx'
import { pct, pctOf, sumCounts } from './ai-skills/logic'
import { groupChips, groupSkills } from './ai-skills/groups'
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
const grp = ref('')
const showEmpty = ref(false)
const collapsed = ref<Set<string>>(new Set())
const groups = computed(() => data.value?.groups ?? [])
const chips = computed(() => groupChips(groups.value, skills.value))
const blocks = computed(() => groupSkills(groups.value, skills.value, { group: grp.value, q: q.value, use: use.value, showEmpty: showEmpty.value }))
const shownN = computed(() => blocks.value.reduce((n, b) => n + b.skills.length, 0))
// 搜索时自动展开有匹配的组
const isOpen = (id: string) => !!q.value.trim() || !collapsed.value.has(id)
function toggle(id: string): void {
  const n = new Set(collapsed.value)
  if (n.has(id)) n.delete(id)
  else n.add(id)
  collapsed.value = n
}
const gName = (b: { id: string; title: Record<string, string> }) => L(b.title) || (b.id === 'other' ? T('grp.other') : b.id)
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
        <AiOffHint v-if="!data.ai.configured" :reason="data.ai.reason ?? undefined" style="margin-bottom: 14px" data-testid="sk-ai-off"><div class="small muted">{{ T('aiOff.list') }}</div></AiOffHint>

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
            <label class="check small"><input v-model="showEmpty" type="checkbox" data-testid="sk-show-empty"><span>{{ T('grp.showEmpty') }}</span></label>
            <span class="grow" />
            <Bits kind="legend" />
          </div>
          <div v-if="chips.length > 1" class="grp-chips" role="group" :aria-label="T('grp.label')" data-testid="sk-groups">
            <button type="button" class="gchip" :aria-pressed="!grp" data-testid="sk-group-all" @click="grp = ''">{{ T('grp.all') }} <b>{{ skills.length }}</b></button>
            <button v-for="c in chips" :key="c.id" type="button" class="gchip" :aria-pressed="grp === c.id" :data-testid="`sk-group-${c.id}`" @click="grp = grp === c.id ? '' : c.id">{{ gName(c) }} <b>{{ c.n }}</b></button>
          </div>
          <div class="tbl-wrap">
            <table class="tbl sk-tbl" data-testid="sk-table">
              <thead><tr>
                <th>{{ T('col.skill') }}</th><th>{{ T('col.users') }}</th><th>{{ T('col.model') }}</th><th>{{ T('col.on') }}</th><th>{{ T('col.ver') }}</th>
                <th class="num">{{ T('col.calls') }}</th><th>{{ T('col.rate') }}</th><th class="num">{{ T('col.blocked') }}</th><th>{{ T('col.feedback') }}</th><th class="num">{{ T('col.reg') }}</th><th />
              </tr></thead>
              <tbody v-for="b in blocks" :key="b.group.id" class="grp" :data-group="b.group.id" data-testid="sk-group-block">
                <tr class="grp-h">
                  <td colspan="11">
                    <button type="button" class="grp-t" :aria-expanded="isOpen(b.group.id)" :title="isOpen(b.group.id) ? T('grp.collapse') : T('grp.expand')" :data-testid="`sk-group-toggle-${b.group.id}`" @click="toggle(b.group.id)">
                      <Icon :name="isOpen(b.group.id) ? 'chevD' : 'chevR'" small /><span>{{ gName(b.group) }}</span><span class="grp-n">{{ b.skills.length === b.total ? T('grp.n', { n: b.total }) : `${b.skills.length} / ${b.total}` }}</span>
                    </button>
                  </td>
                </tr>
                <tr v-if="isOpen(b.group.id) && !b.total"><td colspan="11" class="faint small grp-empty">{{ T('grp.empty') }}</td></tr>
                <template v-if="isOpen(b.group.id)">
                <tr v-for="s in b.skills" :key="s.id" :class="{ 'is-off': !s.enabled }" :data-skill="s.id" data-testid="sk-row">
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
                </template>
              </tbody>
              <tbody v-if="!shownN && !blocks.length"><tr><td colspan="11" class="muted" style="text-align: center; padding: 24px" data-testid="sk-none">{{ T('list.none') }}</td></tr></tbody>
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

<style scoped>
.grp-chips { display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 12px; border-bottom: 1px solid var(--line); }
.gchip { display: inline-flex; align-items: center; gap: 5px; height: 26px; padding: 0 10px; border-radius: 13px; border: 1px solid var(--line); background: var(--surface); font: 12px var(--font-ui); color: var(--ink-2); cursor: pointer; white-space: nowrap; }
.gchip b { font-weight: 600; color: var(--ink); }
.gchip:hover { border-color: var(--line-strong); }
.gchip[aria-pressed="true"] { background: var(--teal-soft); border-color: var(--teal-line); color: var(--teal-ink); }
.gchip[aria-pressed="true"] b { color: var(--teal-ink); }
.grp-h td { background: var(--surface-2); padding: 0; border-top: 1px solid var(--line); }
.grp-t { display: flex; align-items: center; gap: 8px; width: 100%; padding: 7px 12px; border: 0; background: none; color: var(--ink); font: inherit; font-weight: 600; font-size: 12.5px; cursor: pointer; text-align: left; }
.grp-t:hover { background: var(--surface-3); }
.grp-t:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
.grp-n { font-weight: 500; color: var(--ink-3); font-size: 12px; }
.grp-empty { padding: 10px 12px 10px 34px; }
</style>
