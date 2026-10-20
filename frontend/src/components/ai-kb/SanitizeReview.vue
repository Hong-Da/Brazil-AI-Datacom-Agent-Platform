<script setup lang="ts">
/**
 * 脱敏复核（M8-5，预览 DevelopDocs/ui-preview/M8/compliance.html“配置脱敏”）：设备配置分析页里打开的区块。
 * skill sanitize-review 读未脱敏原文，只允许本地模型：运行前先查 /ai/kb/gate，当前生效的 AI 接口不是本地模型时
 * 不显示运行入口，只显示原因（入口按钮置灰但可点开看原因）；后端在运行时也会再拦一次（409 ai_kb.local_only）。
 * 左侧是当前版本的配置（已按规则脱敏），AI 标出的行紫色、已加入替换的行青绿；下方列出本项目已采纳的脱敏补充。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { errorText, get } from '@/api'
import Icon from '@/components/Icon.vue'
import AiSuggestPanel from '@/components/ai-suggest/AiSuggestPanel.vue'
import AiEntryButton from '@/components/ai-suggest/AiEntryButton.vue'
import { projectPath, query, type ListResult, type Suggestion } from '@/components/ai-suggest/logic'
import { useProject } from '@/stores/project'
import { gateBlocked, sanitizeScope, type Gate } from './logic'

const props = defineProps<{ deviceId: number }>()
const emit = defineEmits<{ close: [] }>()
const project = useProject()
const P = (path: string) => projectPath(project.ref ?? '', path)

const gate = ref<Gate | null>(null)
const gateErr = ref('')
const showWhy = ref(true)
const redact = ref<string[]>([])
const redactErr = ref('')
const lines = ref<string[]>([])
const source = ref('')
const items = ref<Suggestion[]>([])
const state = ref('loading')
const panel = ref<InstanceType<typeof AiSuggestPanel> | null>(null)
const blocked = computed(() => gateBlocked(gate.value))
const scope = computed(() => sanitizeScope(props.deviceId))

/** 行号 → 'flag'（AI 标出、待处理）/ 'fixed'（已加入替换） */
const marks = computed(() => {
  const m: Record<number, 'flag' | 'fixed'> = {}
  for (const it of items.value) {
    const n = Number((it.content ?? {}).line ?? 0)
    if (!n) continue
    if (it.status === 'adopted') m[n] = 'fixed'
    else if (it.status === 'pending' && it.check_status !== 'reject' && m[n] !== 'fixed') m[n] = 'flag'
  }
  return m
})

async function loadGate(): Promise<void> {
  gateErr.value = ''
  try { gate.value = await get<Gate>(P(`/ai/kb/gate${query({ skill: 'sanitize-review' })}`)) } catch (e) { gateErr.value = errorText(e) }
}
async function loadRedact(): Promise<void> {
  redactErr.value = ''
  try { redact.value = (await get<{ patterns: string[] }>(P('/ai/kb/sanitize-redact'))).patterns } catch (e) { redactErr.value = errorText(e) }
}
async function loadText(): Promise<void> {
  try {
    const v = await get<{ versions: { id: number; current?: boolean; latest?: boolean }[] }>(`/devices/${props.deviceId}/versions`)
    const cur = v.versions.find((x) => x.current) ?? v.versions.find((x) => x.latest) ?? v.versions[0]
    if (!cur) return
    const t = await get<{ text: string; source_name: string }>(`/devices/${props.deviceId}/versions/${cur.id}/text`)
    lines.value = t.text.split('\n')
    source.value = t.source_name
  } catch { lines.value = [] }
}
async function loadItems(): Promise<void> {
  try { items.value = (await get<ListResult>(P(`/ai/suggestions${query({ skill: 'sanitize-review', scope: scope.value, limit: 200 })}`))).items } catch { items.value = [] }
}
async function loadAll(): Promise<void> {
  await project.ensure()
  await loadGate()
  await loadRedact()
  await loadItems()
  await loadText()
}
function onState(s: string): void {
  state.value = s
  if (s === 'done' || s === 'empty') void loadItems()
  if (s === 'failed') void loadGate() // 运行时被拦（409 ai_kb.local_only）：AI 选择可能刚改过，重新检查
}
function onChanged(): void { void loadRedact(); void loadItems() }
async function run(): Promise<void> {
  await loadGate()
  if (blocked.value) { showWhy.value = true; return }
  await nextTick()
  await panel.value?.start()
}
function jumpLine(n: number): void {
  document.querySelector(`[data-san-line="${n}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
}
watch(() => props.deviceId, () => void loadAll())
onMounted(loadAll)
</script>

<template>
  <section class="panel san" data-testid="san-review">
    <div class="hostbar">
      <h3><Icon name="sanitize" small /> {{ $t('kb-ai.san.title') }}</h3>
      <span v-if="source" class="mono small faint">{{ source }}</span>
      <span class="localonly"><Icon name="lock" small />{{ $t('kb-ai.san.localOnly') }}</span>
      <span class="ml-auto" />
      <button v-if="blocked" class="btn btn-sm san-off" type="button" :aria-expanded="showWhy" data-testid="san-entry-off" @click="showWhy = !showWhy">
        <Icon name="spark" small />{{ $t('ai-suggest.btn') }}<span class="offdot">{{ $t('kb-ai.san.notLocal') }}</span>
      </button>
      <AiEntryButton v-else-if="gate" :skills="['sanitize-review']" :busy="state === 'running'" small @run="run" />
      <button class="btn btn-sm btn-ghost" type="button" data-testid="san-close" @click="emit('close')"><Icon name="x" small /></button>
    </div>

    <div class="san-b">
      <div class="notice info"><Icon name="info" /><div class="grow small">{{ $t('kb-ai.san.note') }}</div></div>
      <div v-if="gateErr" class="notice err" data-testid="san-gate-err"><Icon name="err" /><div class="grow small">{{ gateErr }}</div><button class="btn btn-xs" type="button" @click="loadGate">{{ $t('c.retry') }}</button></div>
      <div v-if="blocked && showWhy" class="notice warn" data-testid="san-gate" :data-provider="gate?.provider ?? ''">
        <Icon name="lock" />
        <div class="grow">
          <b>{{ $t('ai-suggest.localOnly') }}</b>
          <div class="small">{{ $t('ai-suggest.localOnlyD', { p: gate?.provider ?? '—', c: gate?.connection ?? '—' }) }}</div>
          <div class="toolbar mt8"><router-link class="btn btn-sm" :to="{ name: 'my-ai' }"><Icon name="plug" small />{{ $t('kb-ai.san.toMyAi') }}</router-link>
            <button class="btn btn-sm btn-ghost" type="button" data-testid="san-gate-recheck" @click="loadGate"><Icon name="refresh" small />{{ $t('kb-ai.san.recheck') }}</button></div>
        </div>
      </div>

      <div class="hostgrid" :class="{ one: blocked || !gate }">
        <div class="san-l">
          <div class="mini-h"><span>{{ $t('kb-ai.san.output') }}</span><span class="meta">{{ $t('kb-ai.san.legend') }}</span></div>
          <div class="code-box" data-testid="san-code">
            <div v-if="!lines.length" class="empty"><p>{{ $t('c.loading') }}</p></div>
            <div v-for="(ln, i) in lines" v-else :key="i" class="l" :class="marks[i + 1]" :data-san-line="i + 1">
              <span class="n">{{ i + 1 }}</span><span class="t">{{ ln }}</span>
            </div>
          </div>
          <div class="mini-h mt12"><span>{{ $t('kb-ai.san.redactT') }}</span><span class="meta">{{ $t('kb-ai.san.redactD') }}</span></div>
          <div v-if="redactErr" class="notice err"><Icon name="err" /><div class="grow small">{{ redactErr }}</div></div>
          <ul v-else class="redact" data-testid="san-redact-list">
            <li v-if="!redact.length" class="small faint">{{ $t('kb-ai.san.redactNone') }}</li>
            <li v-for="(r, i) in redact" :key="i" data-testid="san-redact-item"><code class="mono">{{ r }}</code></li>
          </ul>
          <div v-if="Object.keys(marks).length" class="small faint mt8">
            {{ $t('kb-ai.san.flagged') }}
            <button v-for="n in Object.keys(marks).map(Number)" :key="n" class="link-btn mono" type="button" @click="jumpLine(n)">L{{ n }}</button>
          </div>
        </div>
        <AiSuggestPanel v-if="gate && !blocked" ref="panel" skill="sanitize-review" :params="{ device_id: deviceId }" :scope="scope" @state="onState" @changed="onChanged" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.san { margin-bottom: 12px; }
.hostbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 9px 12px; border-bottom: 1px solid var(--line); }
.hostbar h3 { font-size: 13.5px; margin-right: 6px; display: inline-flex; gap: 6px; align-items: center; }
.localonly { display: inline-flex; gap: 5px; align-items: center; height: 22px; padding: 0 8px; border-radius: 11px; font-size: 11.5px; font-weight: 600; color: var(--teal-ink); border: 1px solid var(--teal-line); background: var(--teal-soft); }
.san-off { opacity: .6; }
.offdot { font-size: 10.5px; color: var(--ink-3); margin-left: 4px; }
.san-b { padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.hostgrid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(380px, 460px); gap: 12px; align-items: start; }
.hostgrid.one { grid-template-columns: minmax(0, 1fr); }
@media (max-width: 1100px) { .hostgrid { grid-template-columns: minmax(0, 1fr); } }
.san-l { min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.mini-h { display: flex; gap: 8px; align-items: baseline; font-size: 12px; font-weight: 600; color: var(--ink-2); }
.mini-h .meta { font-weight: 400; color: var(--ink-3); font-size: 11.5px; }
.code-box { border: 1px solid var(--line); border-radius: 6px; max-height: 420px; overflow: auto; font: 12px/20px var(--font-mono); background: var(--surface); }
.code-box .l { display: grid; grid-template-columns: 44px minmax(0, 1fr); gap: 8px; padding: 0 8px; }
.code-box .n { color: var(--ink-3); text-align: right; user-select: none; }
.code-box .t { white-space: pre; overflow-wrap: normal; color: var(--ink); }
.code-box .l.flag { background: color-mix(in srgb, var(--violet-soft) 70%, transparent); box-shadow: inset 3px 0 0 var(--violet); }
.code-box .l.flag .n { color: var(--violet); font-weight: 600; }
.code-box .l.fixed { box-shadow: inset 3px 0 0 var(--teal); }
.redact { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.redact code { font-size: 12px; padding: 2px 6px; border-radius: 4px; background: var(--surface-2); border: 1px solid var(--line); overflow-wrap: anywhere; }
.link-btn { margin-left: 6px; }
</style>
