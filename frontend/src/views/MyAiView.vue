<script setup lang="ts">
/** 我的 AI（REQ-040）：选择 AI 来源（自动 / 某个公共接口 / 个人 API / 不使用）、当前生效来源、个人接口概览（在 /me/ai/personal 编辑）、
 *  我的用量与调用记录。 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiError, errorText, get, post, put } from '@/api'
import Icon from '@/components/Icon.vue'
import AiOffHint from '@/components/ai-off-hint.vue'
import { useAuth } from '@/stores/auth'
import { useStatus } from '@/stores/status'
import CallsPanel from './ai/CallsPanel.vue'
import UsagePanel from './ai/UsagePanel.vue'
import { autoTarget, choiceValue, chosenClosed, parseChoice, type MyAi, type TestResult } from './ai/logic'

const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`my-ai.${k}`, p ?? {})
const A = (k: string, p?: Record<string, unknown>) => t(`ai-settings.${k}`, p ?? {})
const auth = useAuth()
const status = useStatus()
const viaToken = computed(() => auth.me?.via === 'token')

const my = ref<MyAi | null>(null)
const loading = ref(true)
const loadErr = ref('')
const picked = ref('auto')

function apply(m: MyAi): void {
  my.value = m
  picked.value = choiceValue(m.choice, m.connection_id)
}
async function load(): Promise<void> {
  loading.value = true
  loadErr.value = ''
  try {
    apply(await get<MyAi>('/me/ai'))
  } catch (e) {
    loadErr.value = errorText(e)
  } finally {
    loading.value = false
  }
}

const closed = computed(() => !!my.value && chosenClosed(my.value))
const auto = computed(() => (my.value ? autoTarget(my.value) : null))
const dirty = computed(() => !!my.value && picked.value !== choiceValue(my.value.choice, my.value.connection_id))
const needPersonal = computed(() => picked.value === 'personal' && !my.value?.personal)

const saving = ref(false)
const saveErr = ref('')
const savedMsg = ref(false)
async function save(): Promise<void> {
  saveErr.value = ''
  savedMsg.value = false
  if (needPersonal.value) { saveErr.value = T('errPersonalNeeded'); return }
  if (!dirty.value) return
  saving.value = true
  try {
    apply(await put<MyAi>('/me/ai', parseChoice(picked.value)))
    savedMsg.value = true
    testE.value = null
    void status.refresh()
  } catch (e) {
    const d = e instanceof ApiError ? (e.data as { error?: string } | null) : null
    saveErr.value = d?.error ? `${errorText(e)}：${d.error}` : errorText(e)
  } finally {
    saving.value = false
  }
}
function discard(): void { if (my.value) apply(my.value); saveErr.value = '' }

// ---------- 测试当前生效的接口 ----------
const testE = ref<{ ok: boolean; text: string } | 'running' | null>(null)
const callsRef = ref<InstanceType<typeof CallsPanel> | null>(null)
async function testEffective(): Promise<void> {
  testE.value = 'running'
  const t0 = performance.now()
  try {
    const r = await post<TestResult>('/me/ai/test', { target: 'effective' })
    testE.value = { ok: true, text: A('testOk', { m: r.model, ms: Math.round(performance.now() - t0), i: r.tokens_in, o: r.tokens_out }) }
  } catch (e) {
    testE.value = { ok: false, text: A('testFail', { e: errorText(e) }) }
  }
  void callsRef.value?.load()
}

const eff = computed(() => my.value?.effective ?? null)
const effKind = computed(() => {
  const e = eff.value
  if (!e?.configured) return ''
  if (e.source === 'personal') return T('effPersonal')
  return e.choice === 'auto' ? T('effAuto') : T('effConn')
})
const LOGO: Record<string, string> = { anthropic: 'A', openai: 'OA', local: 'L' }
const provName = (p: string | null | undefined) => (p && ['anthropic', 'openai', 'local'].includes(p) ? A(`p_${p}`) : p ?? '—')

onMounted(load)
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="ph">
        <div class="ph-text">
          <h1>{{ T('title') }}</h1>
          <p class="ph-sub">{{ T('sub') }}</p>
        </div>
        <div v-if="my && !viaToken" class="ph-actions">
          <span v-if="dirty" class="small" style="color: var(--amber-ink)" data-testid="my-ai-dirty">{{ T('unsaved') }}</span>
          <span v-else-if="savedMsg" class="small" style="color: var(--teal-ink)" data-testid="my-ai-saved">{{ T('saved') }}</span>
          <button class="btn" :disabled="!dirty || saving" data-testid="my-ai-discard" @click="discard">{{ T('discard') }}</button>
          <button class="btn btn-primary" :disabled="!dirty || saving" data-testid="my-ai-save" @click="save">{{ $t('c.save') }}</button>
        </div>
      </div>

      <div v-if="loading" class="panel"><div class="empty">{{ $t('c.loading') }}</div></div>
      <div v-else-if="loadErr || !my" class="panel">
        <div class="empty"><p>{{ loadErr }}</p><button class="btn" data-testid="my-ai-retry" @click="load"><Icon name="refresh" small />{{ $t('c.retry') }}</button></div>
      </div>

      <template v-else>
        <div v-if="closed" class="closed-bar" role="alert" data-testid="my-ai-closed">
          <Icon name="warn" />
          <div class="grow"><b>{{ T('closedT') }}</b><span class="small">{{ T('closedD') }}</span></div>
        </div>
        <div v-if="viaToken" class="notice info" style="margin-bottom: 14px"><Icon name="key" /><div class="grow small">{{ T('tokenNote') }}</div></div>
        <div v-if="saveErr" class="notice err" style="margin-bottom: 14px" data-testid="my-ai-error">
          <Icon name="err" /><div class="grow small">{{ saveErr }}</div>
          <router-link v-if="needPersonal" class="btn btn-sm" :to="{ name: 'my-ai-personal' }">{{ T('setupP') }}</router-link>
        </div>

        <div class="grid g-side collapse">
          <div class="stack">
            <section v-if="!viaToken" class="panel">
              <div class="panel-h"><h2>{{ T('srcT') }}</h2></div>
              <div class="panel-b">
                <div class="src-list" role="radiogroup" data-testid="my-ai-sources">
                  <label class="src" :class="{ 'is-on': picked === 'auto' }" data-testid="my-ai-src-auto">
                    <input v-model="picked" type="radio" name="src" value="auto">
                    <span class="lg muted"><Icon name="spark" small /></span>
                    <div><div class="t">{{ T('auto') }} <span class="tag small-tag">{{ T('autoTag') }}</span></div><div class="d">{{ auto ? T('autoTo', { n: auto.name }) : T('autoNone') }}</div></div>
                  </label>

                  <div class="src-sep">{{ my.is_admin ? T('adminSep') : T('pubSep') }}</div>
                  <div v-if="!my.options.length" class="small faint" style="padding: 2px" data-testid="my-ai-no-public">{{ T('noPublic') }}</div>
                  <label v-for="o in my.options" :key="o.id" class="src" :class="{ 'is-on': picked === `c:${o.id}` }" :data-testid="`my-ai-src-${o.name}`">
                    <input v-model="picked" type="radio" name="src" :value="`c:${o.id}`">
                    <span class="lg" :class="o.provider">{{ LOGO[o.provider] ?? '?' }}</span>
                    <div><div class="t">{{ o.name }} <span v-if="!o.public" class="tag small-tag">{{ T('notPublic') }}</span></div><div class="d mono">{{ provName(o.provider) }} · {{ o.model }}</div></div>
                  </label>
                  <label v-if="closed" class="src" :class="{ 'is-bad': picked === `c:${my.connection_id}` }" data-testid="my-ai-src-closed">
                    <input v-model="picked" type="radio" name="src" :value="`c:${my.connection_id}`" disabled>
                    <span class="lg muted"><Icon name="lock" small /></span>
                    <div><div class="t"><s>{{ T('closedRow', { id: my.chosen_name ?? (my.connection_id ? `#${my.connection_id}` : '—') }) }}</s> <span class="tag t-amber small-tag">{{ T('closedTag') }}</span></div><div class="d">{{ T('closedPick') }}</div></div>
                  </label>

                  <div class="src-sep">{{ T('otherSep') }}</div>
                  <label class="src" :class="{ 'is-on': picked === 'personal' }" data-testid="my-ai-src-personal">
                    <input v-model="picked" type="radio" name="src" value="personal">
                    <span class="lg personal"><Icon name="user" small /></span>
                    <div>
                      <div class="t">{{ T('personal') }}</div>
                      <div class="d">
                        <template v-if="my.personal">{{ my.personal.api_key_set ? T('personalSet', { p: provName(my.personal.provider), m: my.personal.model }) : T('personalSetNoKey', { p: provName(my.personal.provider), m: my.personal.model }) }}</template>
                        <template v-else>{{ T('personalNone') }}</template>
                      </div>
                    </div>
                    <router-link class="btn btn-sm" :to="{ name: 'my-ai-personal' }" data-testid="my-ai-edit-personal" @click.stop>{{ my.personal ? T('editP') : T('setupP') }}</router-link>
                  </label>
                  <label class="src" :class="{ 'is-on': picked === 'none' }" data-testid="my-ai-src-none">
                    <input v-model="picked" type="radio" name="src" value="none">
                    <span class="lg muted"><Icon name="minus" small /></span>
                    <div><div class="t">{{ T('none') }}</div><div class="d">{{ T('noneD') }}</div></div>
                  </label>
                </div>
              </div>
            </section>

            <UsagePanel mine :title="T('tabUsage')" />
            <CallsPanel ref="callsRef" mine :title="T('callsT')" :foot="T('callsFoot')" />
          </div>

          <div class="stack">
            <section class="panel" data-testid="my-ai-effective">
              <div class="panel-h"><h2>{{ T('effT') }}</h2></div>
              <div v-if="eff?.configured" class="eff">
                <div class="big">
                  <span class="dot" />
                  <div>
                    <b data-testid="my-ai-eff-name">{{ eff.source === 'personal' ? T('personal') : eff.connection?.name }}</b>
                    <div class="small faint">{{ effKind }}<template v-if="eff.connection"> · {{ eff.connection.public ? T('effPublic') : T('effAdminOnly') }}</template></div>
                  </div>
                </div>
                <dl class="kv">
                  <dt>{{ T('type') }}</dt><dd>{{ provName(eff.provider) }}</dd>
                  <dt>{{ T('model') }}</dt><dd>{{ eff.model ?? '—' }}</dd>
                </dl>
              </div>
              <div v-else class="panel-b">
                <AiOffHint :reason="eff?.reason ?? null" no-link />
              </div>
              <div class="panel-f">
                <button class="btn btn-sm" :disabled="!eff?.configured || dirty || testE === 'running'" data-testid="my-ai-test-effective" @click="testEffective">
                  <Icon name="refresh" small />{{ testE === 'running' ? T('testing') : T('testE') }}
                </button>
                <span v-if="testE && testE !== 'running'" class="small" :style="{ color: testE.ok ? 'var(--teal-ink)' : 'var(--red-ink)' }" data-testid="my-ai-test-effective-result">{{ testE.text }}</span>
              </div>
            </section>
            <section class="panel">
              <div class="panel-h"><h2>{{ T('howT') }}</h2></div>
              <div class="panel-b how"><span v-for="i in 4" :key="i">{{ T(`how${i}`) }}</span></div>
            </section>
          </div>
        </div>
      </template>
    </div>
  </main>
</template>

<style scoped>
.src-list { display: flex; flex-direction: column; gap: 8px; }
.src { display: grid; grid-template-columns: 18px 30px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); cursor: pointer; }
.src:hover { border-color: var(--line-strong); }
.src input { accent-color: var(--teal); margin: 0; }
.src.is-on { border-color: var(--teal-line); background: color-mix(in srgb, var(--teal-soft) 40%, var(--surface)); box-shadow: inset 3px 0 0 var(--teal); }
.src.is-bad { border-color: var(--amber-line); background: color-mix(in srgb, var(--amber-soft) 50%, var(--surface)); box-shadow: inset 3px 0 0 var(--amber); cursor: default; }
.src .t { font-weight: 600; font-size: 13.5px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.src .d { font-size: 12px; color: var(--ink-2); margin-top: 2px; overflow-wrap: anywhere; }
.src-sep { font-size: 11px; color: var(--ink-3); text-transform: uppercase; letter-spacing: .06em; margin: 6px 2px 0; }
.lg { width: 30px; height: 30px; border-radius: 7px; display: inline-flex; align-items: center; justify-content: center; font: 700 11px var(--font-ui); color: var(--surface); flex: none; }
.lg.anthropic { background: var(--amber-ink); }
.lg.openai { background: var(--blue-ink); }
.lg.local { background: var(--ink-2); }
.lg.muted { background: transparent; color: var(--ink-3); border: 1px dashed var(--line-strong); }
.lg.personal { background: transparent; color: var(--teal-ink); border: 1.5px solid var(--teal-line); }
.small-tag { font-size: 11px; height: 19px; font-weight: 500; }
.closed-bar { display: flex; gap: 12px; align-items: flex-start; padding: 12px 14px; border: 1px solid var(--amber-line); background: var(--amber-soft); border-radius: var(--r-panel); color: var(--ink); margin-bottom: 14px; }
.closed-bar > .ico { color: var(--amber-ink); flex: none; margin-top: 2px; }
.closed-bar b { display: block; }
.closed-bar .small { color: var(--ink-2); }
.eff { padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.eff .big { display: flex; gap: 12px; align-items: center; }
.eff .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--teal); box-shadow: 0 0 0 4px var(--teal-soft); flex: none; }
.eff .big b { font-size: 15px; }
.how { display: flex; flex-direction: column; gap: 8px; font-size: 12.5px; color: var(--ink-2); }
.panel-f { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
@media (max-width: 1100px) { .g-side.collapse { grid-template-columns: minmax(0, 1fr); } }
</style>
