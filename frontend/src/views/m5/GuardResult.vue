<script setup lang="ts">
/**
 * 护栏结果（AI 生成配置与“校验粘贴的配置”共用）：五个阶段的状态条、逐行 ✓ / ✕ / !、拦截原因与注意事项、结论条。
 * 被拦截时“交给增量变更”不可用；通过后可以交给增量变更，或直接查看护栏附带的增量变更脚本。
 */
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { useTerms } from '@/stores/terms'
import { issueGroups, stageViews, type GuardResult } from './ask'

const props = defineProps<{ g: GuardResult; ai: boolean; rounds?: number[]; round?: number; busy?: boolean }>()
const emit = defineEmits<{ (e: 'round', n: number): void; (e: 'regen'): void; (e: 'edit'): void; (e: 'handoff'): void; (e: 'copy', s: string): void }>()
const terms = useTerms()

const stages = computed(() => stageViews(props.g, props.ai))
const groups = computed(() => issueGroups(props.g.issues ?? []))
const sel = ref<string | null>(null)
const selLines = computed(() => new Set(props.g.issues.find((i) => i.id === sel.value)?.lines ?? []))
const mark = (s: string) => (s === 'ok' ? '✓' : s === 'bad' ? '✕' : s === 'warn' ? '!' : '')
const showScript = ref(false)
const blocked = computed(() => props.g.verdict !== 'passed')
const keep = computed(() => props.g.lines.filter((l) => l.status !== 'skip'))
function pickLine(issues: string[]): void { if (issues.length) sel.value = issues[0] }
</script>

<template>
  <div class="pipe" data-testid="guard-stages">
    <div v-for="(s, i) in stages" :key="s.key" :class="`st-${s.cls}`" :data-testid="`guard-stage-${s.key}`">
      <div class="pn"><span class="faint">{{ i + 1 }}</span>{{ $t(`ask.stage.${s.key}${s.key === 'gen' && !ai ? 'Src' : ''}`) }}</div>
      <div class="pd">{{ $t(`ask.stageD.${s.key}${s.key === 'gen' && !ai ? 'Src' : ''}`) }}</div>
      <div class="pr">
        <template v-if="s.key === 'gen'"><span v-if="ai" class="ailabel"><Icon name="spark" small />AI</span><span class="tag">{{ $t('ask.nLines', { n: s.lines }) }}</span></template>
        <span v-else-if="s.key === 'graph'" class="vs ok">{{ $t('ask.inGraph', { n: s.lines }) }}</span>
        <span v-else-if="s.skipped" class="tag">{{ $t('ask.skipped') }}</span>
        <span v-else-if="s.bad" class="vs bad">{{ $t('ask.blockedN', { n: s.bad }) }}</span>
        <span v-else-if="s.warn" class="vs fix">{{ $t('ask.warnN', { n: s.warn }) }}</span>
        <span v-else class="vs ok">{{ $t('ask.passed') }}</span>
      </div>
    </div>
  </div>

  <div v-if="g.error" class="notice err mt12"><Icon name="err" /><div class="grow">{{ g.error.key }}</div></div>

  <div class="gw">
    <section class="panel">
      <div class="panel-h">
        <h2>{{ ai ? $t('ask.aiConfig') : $t('ask.pastedConfig') }}</h2>
        <span v-if="ai" class="ailabel"><Icon name="spark" small />AI</span>
        <span v-if="rounds && rounds.length > 1" class="rounds">{{ $t('ask.round') }} <span class="seg"><button v-for="n in rounds" :key="n" type="button" :aria-pressed="round === n" :data-testid="`guard-round-${n}`" @click="emit('round', n)">{{ n }}</button></span></span>
      </div>
      <div class="glines" :class="{ aiblk: ai }" data-testid="guard-lines">
        <div v-for="l in keep" :key="l.no" class="gl" :class="[l.status, { 'is-sel': l.issues.some((x) => x === sel) || selLines.has(l.no) }]" :data-status="l.status" @click="pickLine(l.issues)">
          <span class="no">{{ l.no }}</span><span class="mk">{{ mark(l.status) }}</span>
          <span class="t">{{ l.text }}<span v-if="l.nodes.length" class="node" :title="l.nodes.join('\n')">→ {{ terms.describe(l.nodes[0]) }}</span></span>
        </div>
      </div>
      <div class="panel-f small faint">{{ $t('ask.lineLegend') }}</div>
    </section>

    <section class="panel" aria-label="Issues" data-testid="guard-issues">
      <div v-if="!groups.length" class="empty"><Icon name="ok" /><h3>{{ $t('ask.allPassed', { n: g.summary.lines }) }}</h3><p>{{ $t('ask.allPassedText') }}</p></div>
      <template v-for="gr in groups" :key="gr.status">
        <div class="igh"><span class="vs" :class="gr.status === 'warn' ? 'fix' : gr.status">{{ $t(`ask.grp.${gr.status}`) }}</span><span class="cnt">{{ gr.items.length }}</span></div>
        <div v-for="it in gr.items" :key="it.id" class="iss" :class="{ 'is-sel': sel === it.id }" tabindex="0" data-testid="guard-issue" @click="sel = it.id" @keydown.enter="sel = it.id">
          <div class="ih"><b>{{ $t(`ask.rule.${it.rule}`) !== `ask.rule.${it.rule}` ? $t(`ask.rule.${it.rule}`) : it.rule }}</b><span class="tag">{{ $t(`ask.stage.${it.stage}`) }}</span><span v-if="it.line" class="ln">{{ $t('ask.lineN', { n: it.line }) }}</span></div>
          <div class="ib">{{ it.text }}</div>
          <div v-if="it.fix" class="fix"><Icon name="wand" small /><span>{{ $t('ask.suggest') }}<code>{{ it.fix }}</code></span></div>
          <div class="irule mt8">{{ $t('ask.ruleId') }} {{ it.stage }}.{{ it.rule }}</div>
        </div>
      </template>
    </section>
  </div>

  <div class="verdict" :class="blocked ? 'bad' : 'ok'" data-testid="guard-verdict" :data-verdict="g.verdict">
    <div class="vt"><Icon :name="blocked ? 'err' : 'ok'" />{{ blocked ? $t('ask.blocked', { n: g.summary.bad }) : $t('ask.verdictOk') }}</div>
    <div class="vd">{{ blocked ? $t('ask.blockedText') : g.summary.warn ? $t('ask.okWarn', { n: g.summary.warn }) : $t('ask.okText') }}</div>
    <template v-if="blocked">
      <button v-if="ai" class="btn btn-primary" type="button" :disabled="busy" data-testid="guard-regen" @click="emit('regen')"><Icon name="spark" small />{{ $t('ask.regen') }}</button>
      <button class="btn" type="button" data-testid="guard-edit" @click="emit('edit')"><Icon name="sliders" small />{{ $t('ask.editRecheck') }}</button>
      <button class="btn" type="button" disabled :title="$t('ask.hasBlocked')"><Icon name="branch" small />{{ $t('ask.toChange') }}</button>
    </template>
    <template v-else>
      <button class="btn btn-primary" type="button" data-testid="guard-handoff" @click="emit('handoff')"><Icon name="branch" small />{{ $t('ask.toChange') }}</button>
      <button v-if="g.script?.available" class="btn" type="button" data-testid="guard-script-btn" @click="showScript = !showScript"><Icon name="file" small />{{ showScript ? $t('ask.hideScript') : $t('ask.showScript', { n: g.script.ops ?? 0 }) }}</button>
      <button class="btn" type="button" @click="emit('copy', keep.map((l) => l.text).join('\n'))"><Icon name="copy" small />{{ $t('c.copy') }}</button>
    </template>
  </div>
  <div v-if="showScript && g.script?.available" class="panel mt12" data-testid="guard-script">
    <div class="panel-h"><h3>{{ $t('ask.scriptTitle') }}</h3><span class="small" :style="{ color: g.script.verify_ok ? 'var(--teal-ink)' : 'var(--amber-ink)' }">{{ g.script.verify_ok ? $t('ask.verifyOk') : $t('ask.verifyBad') }}</span><button class="btn btn-xs btn-ghost ml-auto" type="button" @click="emit('copy', g.script.script_plain ?? '')"><Icon name="copy" small />{{ $t('c.copy') }}</button></div>
    <pre class="block script">{{ g.script.script_plain }}</pre>
  </div>
</template>

<style scoped>
.pipe { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); margin-top: 12px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-panel); overflow: hidden; }
.pipe > div { padding: 10px 12px 10px 14px; position: relative; border-left: 1px solid var(--line); min-width: 0; }
.pipe > div:first-child { border-left: 0; }
.pipe .pn { display: flex; gap: 6px; align-items: center; font-size: 12.5px; font-weight: 600; }
.pipe .pd { font-size: 11.5px; color: var(--ink-3); margin-top: 3px; }
.pipe .pr { margin-top: 6px; display: flex; gap: 4px; flex-wrap: wrap; }
.pipe > div.st-bad { box-shadow: inset 0 3px 0 var(--red); }
.pipe > div.st-ok { box-shadow: inset 0 3px 0 var(--teal); }
.pipe > div.st-ai { box-shadow: inset 0 3px 0 var(--ai); }
.pipe > div.st-warn { box-shadow: inset 0 3px 0 var(--amber); }
.gw { display: grid; grid-template-columns: minmax(0, 1fr) 430px; gap: 12px; margin-top: 12px; align-items: start; }
.glines { padding: 6px 0; overflow-x: auto; margin: 8px 0 8px 10px; }
.gl { display: grid; grid-template-columns: 40px 26px minmax(0, 1fr); font: 12px/22px var(--font-mono); cursor: pointer; }
.gl > .no { text-align: right; padding-right: 8px; color: var(--ink-3); background: var(--surface-2); border-right: 1px solid var(--line); user-select: none; font-size: 11px; }
.gl > .mk { display: inline-flex; align-items: center; justify-content: center; font: 700 11px/1 var(--font-ui); }
.gl > .t { white-space: pre; padding-right: 12px; overflow: hidden; text-overflow: ellipsis; }
.gl.ok > .mk { color: var(--teal-ink); }
.gl.bad { background: color-mix(in srgb, var(--red-soft) 75%, transparent); }
.gl.bad > .mk { color: var(--red-ink); }
.gl.bad > .t { text-decoration: underline wavy color-mix(in srgb, var(--red) 60%, transparent); text-underline-offset: 4px; text-decoration-thickness: 1px; }
.gl.warn { background: color-mix(in srgb, var(--amber-soft) 65%, transparent); }
.gl.warn > .mk { color: var(--amber-ink); }
.gl.ctx > .t { color: var(--ink-3); }
.gl.is-sel { box-shadow: inset 3px 0 0 var(--amber); background: var(--hl-line); }
.gl:hover:not(.is-sel) > .t { background: color-mix(in srgb, var(--blue-soft) 55%, transparent); }
.gl .node { color: var(--ink-3); font: 11px var(--font-ui); margin-left: 10px; text-decoration: none; }
.iss { padding: 10px 12px; border-bottom: 1px solid var(--line); cursor: pointer; }
.iss:last-child { border-bottom: 0; }
.iss:hover { background: var(--surface-2); }
.iss.is-sel { background: var(--blue-soft); box-shadow: inset 0 0 0 1.5px var(--sel-ring); }
.iss .ih { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.iss .ih .ln { font: 11px var(--font-mono); color: var(--ink-3); margin-left: auto; }
.iss .ib { font-size: 12.5px; color: var(--ink-2); margin-top: 5px; overflow-wrap: anywhere; }
.iss .fix { margin-top: 6px; font-size: 12px; color: var(--ink-2); display: flex; gap: 6px; align-items: baseline; }
.iss .fix code { background: var(--surface-2); border: 1px solid var(--line); border-radius: 3px; padding: 0 4px; font-size: 11.5px; color: var(--ink); }
.iss .irule { font: 11px var(--font-mono); color: var(--ink-3); }
.igh { padding: 7px 12px; background: var(--surface-2); border-bottom: 1px solid var(--line); font-size: 12px; font-weight: 600; color: var(--ink-2); display: flex; gap: 8px; align-items: center; }
.igh .cnt { margin-left: auto; font-weight: 400; color: var(--ink-3); }
.verdict { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; padding: 12px 14px; margin-top: 12px; border-radius: var(--r-panel); border: 1px solid; }
.verdict.bad { border-color: var(--red-line); background: var(--red-soft); }
.verdict.ok { border-color: var(--teal-line); background: var(--teal-soft); }
.verdict .vt { font: 600 15px var(--font-display); display: flex; gap: 8px; align-items: center; }
.verdict.bad .vt { color: var(--red-ink); }
.verdict.ok .vt { color: var(--teal-ink); }
.verdict .vd { font-size: 12.5px; color: var(--ink-2); flex: 1; min-width: 260px; }
.rounds { display: inline-flex; gap: 6px; align-items: center; font-size: 12px; color: var(--ink-3); margin-left: auto; }
.script { max-height: 360px; overflow: auto; margin: 0; border: 0; border-radius: 0 0 var(--r-panel) var(--r-panel); }
@media (max-width: 1400px) {
  .gw { grid-template-columns: minmax(0, 1fr) 360px; }
  .pipe { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .pipe > div:nth-child(4) { border-left: 0; }
  .pipe > div:nth-child(n+4) { border-top: 1px solid var(--line); }
}
@media (max-width: 1000px) { .gw { grid-template-columns: minmax(0, 1fr); } }
</style>
