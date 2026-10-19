<script setup lang="ts">
/** 工作区右上：问题列表（级别 / 类别筛选、AI 来源与校验状态、被代码拦截的 AI 发现、顺序核查关闭的说明）。 */
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import AiOffHint from '@/components/ai-off-hint.vue'
import AiFeedback from '@/components/ai-feedback.vue'
import { pickLang } from '@/i18n'
import { aiStats, categoriesFor, countByCat, countBySev, filterIssues, SEVERITIES, sortIssues } from './logic'
import type { AiInfo, AiRule, Category, Issue, Kind, Severity } from './types'

const props = defineProps<{
  issues: Issue[]
  kind: Kind
  aiActive: boolean
  aiInfo: AiInfo | null
  aiStale: boolean
  aiRules: AiRule[]
  orderOff: boolean
  sel: string | null
  sev: Set<Severity>
  cat: Set<Category>
}>()
const emit = defineEmits<{
  (e: 'pick', x: Issue): void
  (e: 'update:sev', v: Set<Severity>): void
  (e: 'update:cat', v: Set<Category>): void
  (e: 'reorder'): void
}>()
const { t, locale } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`check-projects.${k}`, p ?? {})

const all = computed(() => sortIssues(props.issues))
const shown = computed(() => filterIssues(all.value, props.sev, props.cat))
const sevN = computed(() => countBySev(all.value))
const catN = computed(() => countByCat(all.value))
const cats = computed(() => categoriesFor(props.kind, props.aiActive, catN.value))
const anyFilter = computed(() => props.sev.size > 0 || props.cat.size > 0)
const stats = computed(() => aiStats(props.aiInfo, all.value))
const ruleTitle = (id: string | null | undefined) => {
  const r = props.aiRules.find((x) => x.id === id)
  return r ? pickLang(r.title, String(locale.value)) : id ?? ''
}

function toggleSev(s: Severity): void {
  const n = new Set(props.sev)
  if (n.has(s)) n.delete(s)
  else n.add(s)
  emit('update:sev', n)
}
function toggleCat(c: Category): void {
  const n = new Set(props.cat)
  if (n.has(c)) n.delete(c)
  else n.add(c)
  emit('update:cat', n)
}
function clear(): void { emit('update:sev', new Set()); emit('update:cat', new Set()) }

const box = ref<HTMLDivElement>()
// 从编辑器选中时把问题滚到可见处
watch(() => props.sel, (id) => {
  void nextTick(() => {
    const el = box.value?.querySelector<HTMLElement>(`[data-issue="${id}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  })
})
</script>

<template>
  <section class="panel iss-p" data-testid="cp-issues">
    <div class="iss-h">
      <div class="t">
        <h2>{{ T('issues') }} <span data-testid="cp-issue-count">{{ all.length }}</span></h2>
        <span class="cnt">
          <span v-for="s in SEVERITIES" :key="s" :class="sevN[s] ? s.charAt(0) : 'zero'" :title="T(`sev.${s}`)"><span class="sevdot" :class="sevN[s] ? s : ''" :style="sevN[s] ? '' : 'background: var(--line-strong)'" /><b>{{ sevN[s] }}</b></span>
        </span>
        <span class="grow" style="flex: 1" />
        <button v-if="anyFilter" class="btn btn-xs btn-ghost" type="button" @click="clear">{{ T('clearFilters') }}</button>
      </div>
      <div class="fchips" data-testid="cp-sev-filter">
        <button v-for="s in SEVERITIES" :key="s" type="button" class="fchip" :class="{ zero: !sevN[s] }" :aria-pressed="sev.has(s)" @click="toggleSev(s)">
          <span class="sevdot" :class="s" />{{ T(`sev.${s}`) }} <b>{{ sevN[s] }}</b>
        </button>
      </div>
      <div class="fchips" data-testid="cp-cat-filter">
        <button v-for="c in cats" :key="c" type="button" class="fchip" :class="{ zero: !catN[c] }" :aria-pressed="cat.has(c)" :data-cat="c" @click="toggleCat(c)">
          {{ T(`cat.${c}`) }} <b>{{ catN[c] || 0 }}</b>
        </button>
      </div>
      <div v-if="aiActive && aiInfo && !aiStale" class="ai-sum" data-testid="cp-ai-sum">
        <Icon name="spark" />
        <div>
          <template v-if="aiInfo.status === 'error'">{{ T('ai.error', { e: aiInfo.error || '' }) }}</template>
          <template v-else-if="aiInfo.status === 'no_rules'">{{ T('ai.noRules') }}</template>
          <AiOffHint v-else-if="aiInfo.status === 'not_configured'" compact />
          <template v-else>
            {{ T('ai.summary', { r: aiInfo.rules?.length ?? 0, p: stats.proposed, s: stats.shown, ok: stats.passed, na: stats.unverifiable }) }}
            <details v-if="stats.rejected" style="display: inline" data-testid="cp-ai-rejected">
              <summary>{{ T('ai.blocked', { n: stats.rejected }) }}</summary>
              <p v-for="(r, i) in aiInfo.rejected" :key="i">
                <span v-if="r.line">{{ T('lineN', { n: r.line }) }} · </span><span v-if="r.rule" class="mono">{{ r.rule }}</span><span v-if="r.rule"> · </span>{{ T(`ai.reason.${r.reason}`) }}
              </p>
            </details>
            <template v-else>{{ T('ai.noneBlocked') }}</template>
          </template>
          <AiFeedback v-if="aiInfo.skill_run" :run-id="aiInfo.skill_run" :skill="aiInfo.skill?.id ?? 'script-review'" kind="finding" style="margin-top: 6px" />
        </div>
      </div>
      <div v-else-if="aiActive && aiStale" class="order-off"><Icon name="spark" /><span>{{ T('ai.stale') }}</span></div>
      <div v-if="orderOff" class="order-off" data-testid="cp-order-off"><Icon name="info" /><span>{{ T('orderOffNote') }}</span></div>
    </div>
    <div ref="box" class="sb">
      <div class="iss">
        <div
          v-for="x in shown" :key="x.id" class="iitem" :class="{ 'is-sel': sel === x.id }" tabindex="0" :data-issue="x.id" :data-cat="x.category" :data-sev="x.severity"
          data-testid="cp-issue" @click="emit('pick', x)" @keydown.enter="emit('pick', x)"
        >
          <span class="sevdot" :class="[x.severity, { ring: x.source === 'ai' && x.status !== 'passed' }]" :style="{ '--c': `var(--sq-${x.severity === 'error' ? 'err' : x.severity === 'warning' ? 'warn' : 'info'})` }" />
          <div class="hd">
            <span class="ln">{{ T('lineN', { n: x.line }) }}</span>
            <span class="sev" :class="x.severity">{{ T(`sev.${x.severity}`) }}</span>
            <template v-if="x.source === 'ai'">
              <span class="ai-mark"><Icon name="spark" />AI</span>
              <span v-if="x.status === 'passed'" class="ls ok">{{ T('ai.passed') }}</span>
              <span v-else class="ls na">{{ T('ai.unverifiable') }}</span>
            </template>
            <span v-else class="cat" :class="`c-${x.category}`">{{ T(`cat.${x.category}`) }}</span>
            <span v-if="x.rule" class="mono faint" style="font-size: 11px" :title="ruleTitle(x.rule)">{{ x.rule }}</span>
          </div>
          <div class="msg">{{ x.text }}</div>
          <div v-if="x.suggestion" class="sug">{{ x.suggestion }}</div>
          <div v-if="x.category === 'order'" class="act"><button class="btn btn-xs" type="button" @click.stop="emit('reorder')"><Icon name="order" small />{{ T('reorderBtn') }}</button></div>
        </div>
        <div v-if="!shown.length" class="iss-empty" data-testid="cp-issues-empty">
          <template v-if="all.length">{{ T('noIssuesFiltered') }}</template>
          <template v-else><Icon name="ok" /> {{ T('noIssuesFound') }}</template>
        </div>
      </div>
    </div>
  </section>
</template>
