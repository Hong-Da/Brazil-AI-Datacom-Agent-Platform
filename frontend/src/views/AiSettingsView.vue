<script setup lang="ts">
/** AI 接口（管理员，REQ-040）：接口概览（名称、类型、公共使用与启用开关、状态、本月用量），点进 /ai/connections/:id 单独设置；
 *  另有“用量统计”（全部用户）与“调用记录”（带用户与接口列）两个分区。超时与 max_tokens 是全局配置，只读展示。 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { errorText, get, put } from '@/api'
import Icon from '@/components/Icon.vue'
import { useStatus } from '@/stores/status'
import CallsPanel from './ai/CallsPanel.vue'
import UsagePanel from './ai/UsagePanel.vue'
import { fmtTokens, taskModels, type Connection, type ConnectionList } from './ai/logic'

const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`ai-settings.${k}`, p ?? {})
const status = useStatus()
const route = useRoute()
const router = useRouter()

type Tab = 'conns' | 'usage' | 'calls'
const tab = computed<Tab>(() => (route.query.tab === 'usage' || route.query.tab === 'calls' ? route.query.tab : 'conns'))
function goTab(v: Tab): void { void router.replace({ query: { ...route.query, tab: v === 'conns' ? undefined : v } }) }

const data = ref<ConnectionList | null>(null)
const loading = ref(true)
const loadErr = ref('')
const conns = computed(() => data.value?.connections ?? [])
const publicN = computed(() => conns.value.filter((c) => c.public && c.enabled).length)
const maxTok = computed(() => Math.max(1, ...conns.value.map((c) => c.usage.tokens_in + c.usage.tokens_out)))

async function load(): Promise<void> {
  loading.value = true
  loadErr.value = ''
  try {
    data.value = await get<ConnectionList>('/ai/connections')
  } catch (e) {
    loadErr.value = errorText(e)
  } finally {
    loading.value = false
  }
}
async function reload(): Promise<void> {
  try { data.value = await get<ConnectionList>('/ai/connections') } catch (e) { flash(errorText(e)) }
  void status.refresh()
}

const toast = ref('')
let toastTimer = 0
function flash(s: string): void { toast.value = s; window.clearTimeout(toastTimer); toastTimer = window.setTimeout(() => { toast.value = '' }, 2800) }

// 列表里直接切换公共使用与启用；其余设置在单独的设置页
const busy = ref<number | null>(null)
async function toggle(c: Connection, key: 'public' | 'enabled', v: boolean): Promise<void> {
  busy.value = c.id
  try {
    await put<Connection>(`/ai/connections/${c.id}`, { [key]: v })
    if (key === 'public' && !v && c.chosen_by) flash(T('closedToast', { n: c.chosen_by }))
  } catch (e) {
    flash(errorText(e))
  } finally {
    busy.value = null
    await reload()
  }
}
function open(c: Connection): void { void router.push({ name: 'ai-connection', params: { id: String(c.id) } }) }
const LOGO: Record<string, string> = { anthropic: 'A', openai: 'OA', local: 'L' }

onMounted(load)
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.ai-settings') }}</h1>
          <p class="ph-sub">{{ T('sub') }}</p>
        </div>
        <div class="ph-actions">
          <router-link class="btn btn-primary" :to="{ name: 'ai-connection', params: { id: 'new' } }" data-testid="ai-add"><Icon name="plus" small />{{ T('add') }}</router-link>
        </div>
      </div>

      <div class="tabs" role="tablist" data-testid="ai-tabs">
        <button type="button" role="tab" :aria-selected="tab === 'conns'" data-testid="ai-tab-conns" @click="goTab('conns')">{{ T('tabConns') }}</button>
        <button type="button" role="tab" :aria-selected="tab === 'usage'" data-testid="ai-tab-usage" @click="goTab('usage')">{{ T('tabUsage') }}</button>
        <button type="button" role="tab" :aria-selected="tab === 'calls'" data-testid="ai-tab-calls" @click="goTab('calls')">{{ T('tabCalls') }}</button>
      </div>

      <template v-if="tab === 'conns'">
        <section class="panel rule-strip">
          <div><Icon name="globe" /><div><b>{{ T('ruleP') }}</b><span>{{ T('ruleP_d') }}</span></div></div>
          <div><Icon name="shield" /><div><b>{{ T('ruleA') }}</b><span>{{ T('ruleA_d') }}</span></div></div>
          <div><Icon name="lock" /><div><b>{{ T('ruleK') }}</b><span>{{ T('ruleK_d') }}</span></div></div>
        </section>

        <div class="grid g-side collapse mt16">
          <section class="panel" data-testid="ai-connections">
            <div class="panel-h"><h2>{{ T('listT') }}</h2><span v-if="conns.length" class="meta">{{ T('listMeta', { n: conns.length, p: publicN }) }}</span></div>
            <div v-if="loading" class="empty">{{ $t('c.loading') }}</div>
            <div v-else-if="loadErr" class="empty">
              <p>{{ loadErr }}</p>
              <button class="btn" data-testid="ai-retry" @click="load"><Icon name="refresh" small />{{ $t('c.retry') }}</button>
            </div>
            <div v-else-if="!conns.length" class="empty" data-testid="ai-empty">
              <Icon name="spark" />
              <h3>{{ T('emptyT') }}</h3>
              <p>{{ T('emptyD') }}</p>
              <router-link class="btn btn-primary" :to="{ name: 'ai-connection', params: { id: 'new' } }"><Icon name="plus" small />{{ T('add') }}</router-link>
            </div>
            <div v-else class="conn-list">
              <div v-for="c in conns" :key="c.id" class="conn" :class="{ 'is-off': !c.enabled }" :data-testid="`ai-conn-${c.name}`">
                <span class="lg clickable" :class="c.provider" @click="open(c)">{{ LOGO[c.provider] ?? '?' }}</span>
                <div class="cn clickable" @click="open(c)">
                  <div class="t">
                    <router-link :to="{ name: 'ai-connection', params: { id: String(c.id) } }" class="nm" :title="T('openTip')" :data-testid="`ai-conn-open-${c.name}`" @click.stop>{{ c.name }}</router-link>
                    <span v-if="c.is_default" class="tag t-teal small-tag" :title="T('defaultTip')" data-testid="ai-conn-default">{{ T('default') }}</span>
                    <span v-if="!c.enabled" class="tag small-tag">{{ T('disabled') }}</span>
                  </div>
                  <div class="cm"><span class="faint">{{ T(`p_${c.provider}`) }}</span> · {{ c.model }}</div>
                  <div v-if="taskModels(c).length" class="models">
                    <span v-for="[k, m] in taskModels(c)" :key="k" class="m"><i>{{ T(`short_${k}`) }}</i>{{ m }}</span>
                  </div>
                </div>
                <div class="sw" :class="{ 'pub-on': c.public && c.enabled }">
                  <label><span class="switch"><input type="checkbox" :checked="c.public" :disabled="busy === c.id" :data-testid="`ai-conn-public-${c.name}`" @change="toggle(c, 'public', ($event.target as HTMLInputElement).checked)"><span /></span>{{ T('public') }}</label>
                  <span class="k">{{ c.public ? T('publicOn') : T('publicOff') }}</span>
                </div>
                <div class="sw">
                  <label><span class="switch"><input type="checkbox" :checked="c.enabled" :disabled="busy === c.id" :data-testid="`ai-conn-enabled-${c.name}`" @change="toggle(c, 'enabled', ($event.target as HTMLInputElement).checked)"><span /></span>{{ T('enabled') }}</label>
                  <span class="k">{{ T('chosenBy', { n: c.chosen_by }) }}</span>
                </div>
                <div class="use clickable" @click="open(c)">
                  <div class="n">
                    <span>{{ T('calls', { n: c.usage.calls }) }}<template v-if="c.usage.errors"> · <span class="bad">{{ T('callsErr', { n: c.usage.errors }) }}</span></template></span>
                    <b>{{ fmtTokens(c.usage.tokens_in + c.usage.tokens_out) }}</b>
                  </div>
                  <div class="meter"><div class="bar"><i :style="{ width: `${Math.round(((c.usage.tokens_in + c.usage.tokens_out) / maxTok) * 100)}%` }" /></div></div>
                </div>
                <router-link class="btn btn-sm" :to="{ name: 'ai-connection', params: { id: String(c.id) } }" :data-testid="`ai-conn-edit-${c.name}`">{{ T('open') }}<Icon name="chevR" small /></router-link>
              </div>
            </div>
          </section>
          <div class="stack">
            <section class="panel" data-testid="ai-limits">
              <div class="panel-h"><h2>{{ T('limitsT') }}</h2><span class="tag">{{ T('limitsTag') }}</span></div>
              <div class="panel-b">
                <dl class="kv">
                  <dt>{{ T('timeout') }}</dt><dd>{{ data?.limits.timeout ?? '—' }} s</dd>
                  <dt>{{ T('maxTokens') }}</dt><dd>{{ data?.limits.max_tokens ?? '—' }}</dd>
                </dl>
                <p class="small faint mt8">{{ T('limitsNote') }}</p>
              </div>
            </section>
            <section class="panel">
              <div class="panel-h"><h2>{{ T('safetyT') }}</h2><Icon name="shield" small style="color: var(--teal-ink)" /></div>
              <div class="panel-b safety"><span v-for="i in 3" :key="i">{{ T(`safe${i}`) }}</span></div>
            </section>
          </div>
        </div>
      </template>

      <UsagePanel v-else-if="tab === 'usage'" />
      <CallsPanel v-else :title="T('callsT')" :foot="T('callsFoot')" />
    </div>
    <div v-if="toast" class="toast" role="status" data-testid="ai-toast">{{ toast }}</div>
  </main>
</template>

<style scoped>
.rule-strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.rule-strip > div { padding: 12px 16px; border-left: 1px solid var(--line); font-size: 12.5px; color: var(--ink-2); display: flex; gap: 10px; align-items: flex-start; }
.rule-strip > div:first-child { border-left: 0; }
.rule-strip b { color: var(--ink); display: block; margin-bottom: 2px; font-size: 13px; }
.rule-strip .ico { color: var(--teal-ink); flex: none; margin-top: 2px; }
.conn-list { display: flex; flex-direction: column; }
.conn { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto auto minmax(110px, .6fr) auto; gap: 14px; align-items: center; padding: 12px 16px; border-top: 1px solid var(--line); }
.conn:first-child { border-top: 0; }
.conn:hover { background: color-mix(in srgb, var(--surface-2) 60%, transparent); }
.conn.is-off { background: color-mix(in srgb, var(--surface-2) 70%, transparent); }
.conn.is-off .nm, .conn.is-off .cm { color: var(--ink-3); }
.clickable { cursor: pointer; }
.lg { width: 30px; height: 30px; border-radius: 7px; display: inline-flex; align-items: center; justify-content: center; font: 700 11px var(--font-ui); color: var(--surface); flex: none; }
.lg.anthropic { background: var(--amber-ink); }
.lg.openai { background: var(--blue-ink); }
.lg.local { background: var(--ink-2); }
.cn { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.cn .t { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.nm { font-size: 14px; font-weight: 600; color: var(--ink); }
.cm { font: 12px var(--font-mono); color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cm .faint { font-family: var(--font-ui); }
.small-tag { font-size: 11px; height: 19px; }
.models { display: flex; flex-wrap: wrap; gap: 4px; }
.models .m { font: 11px var(--font-mono); color: var(--ink-2); border: 1px solid var(--line); border-radius: 4px; padding: 0 5px; background: var(--surface-2); white-space: nowrap; }
.models .m i { font-style: normal; color: var(--ink-3); font-family: var(--font-ui); margin-right: 3px; }
.sw { display: flex; flex-direction: column; gap: 3px; align-items: flex-start; min-width: 92px; }
.sw label { display: flex; gap: 7px; align-items: center; font-size: 12.5px; cursor: pointer; white-space: nowrap; }
.sw .k { font-size: 11px; color: var(--ink-3); }
.sw.pub-on .k { color: var(--teal-ink); }
.use { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--ink-2); }
.use .n { display: flex; justify-content: space-between; gap: 8px; }
.use b { color: var(--ink); font-variant-numeric: tabular-nums; }
.use .bad { color: var(--red-ink); }
.safety { display: flex; flex-direction: column; gap: 8px; font-size: 12.5px; color: var(--ink-2); }
@media (max-width: 1100px) {
  .rule-strip { grid-template-columns: minmax(0, 1fr); }
  .rule-strip > div { border-left: 0; border-top: 1px solid var(--line); }
  .rule-strip > div:first-child { border-top: 0; }
  .conn { grid-template-columns: 34px minmax(0, 1fr) auto; }
  .conn > .use { grid-column: 2 / -1; }
  .g-side.collapse { grid-template-columns: minmax(0, 1fr); }
}
</style>
