<script setup lang="ts">
/** 按依赖重排（预览 REQ-031/reorder.html）：重排前后并排、连线、每条移动的原因、复检结果；采用后保存为修订。 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText, post } from '@/api'
import { usePrefs } from '@/stores/prefs'
import { useTerms } from '@/stores/terms'
import { reorderColumns, wirePath } from './logic'
import type { ReorderResult, ScriptInfo } from './types'

const props = defineProps<{ pid: number; script: ScriptInfo; content: string; dirty: boolean }>()
const emit = defineEmits<{
  (e: 'back'): void
  (e: 'adopted', content: string, s: ScriptInfo | null): void
  (e: 'revisions'): void
  (e: 'diff', a: string, b: string): void
}>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`check-projects.${k}`, p ?? {})
const prefs = usePrefs()
const terms = useTerms()

const res = ref<ReorderResult | null>(null)
const err = ref('')
const busy = ref(false)
const adopted = ref<ReorderResult | null>(null)
const hot = ref(-1)

const ROW = 24
const HEAD = 40
const WIRE_W = 72
const cols = computed(() => (res.value ? reorderColumns(res.value.original, res.value.script, res.value.moves) : { before: [], after: [] }))
const wires = computed(() => (res.value?.moves ?? []).map((m, i) => ({ i, ...wirePath(m.line, m.new_line, WIRE_W, ROW, HEAD) })))
const svgH = computed(() => HEAD + Math.max(cols.value.before.length, cols.value.after.length) * ROW)
const KIND_COLOR: Record<string, string> = {
  reference: 'var(--e-ref)', referenced_by: 'var(--e-ref)', side_effect: 'var(--e-side)', contains: 'var(--e-pre)', same_target: 'var(--ink-3)', anchor: 'var(--mv)',
}
const DIM = /^\s*(quit|exit|commit|return|end|system-view|configure terminal|#|!)\s*$/

async function load(): Promise<void> {
  err.value = ''
  try {
    res.value = await post<ReorderResult>(`/check-projects/${props.pid}/scripts/${props.script.id}/reorder`, { content: props.content, apply: false, style: terms.style, lang: prefs.lang })
  } catch (e) { err.value = errorText(e) }
}
async function adopt(): Promise<void> {
  busy.value = true
  err.value = ''
  try {
    const r = await post<ReorderResult>(`/check-projects/${props.pid}/scripts/${props.script.id}/reorder`, { content: props.content, apply: true, style: terms.style, lang: prefs.lang })
    adopted.value = r
    res.value = r
    emit('adopted', r.script, null)
  } catch (e) { err.value = errorText(e) } finally { busy.value = false }
}
function diffAdopted(): void {
  const r = adopted.value
  if (!r?.revision) return
  const a = r.before_revision ? `rev:${r.before_revision.id}` : `revseq:${props.script.id}:${r.revision.seq - 1}`
  emit('diff', a, `rev:${r.revision.id}`)
}
const warnText = (w: unknown) => {
  const x = w as { key?: string; params?: Record<string, unknown> }
  return x?.key === 'script_check.reorder.cycle' ? T('reorder.cycle', x.params ?? {}) : JSON.stringify(w)
}
onMounted(load)
</script>

<template>
  <div data-testid="cp-reorder-pane">
    <div class="ph">
      <div class="ph-text">
        <h1>{{ T('view.reorder') }} <span class="mono" style="font-size: 15px; color: var(--ink-2)">{{ script.name }}</span></h1>
        <p class="ph-sub">{{ T('reorder.sub') }}</p>
      </div>
      <div class="ph-actions"><button class="btn" type="button" @click="emit('back')"><Icon name="chevL" small />{{ T('backWs') }}</button></div>
    </div>

    <div v-if="adopted?.revision" class="notice ok adopted" data-testid="cp-adopted">
      <Icon name="ok" />
      <div class="grow"><b>{{ T('reorder.adopted', { n: adopted.revision.seq }) }}</b> <span v-if="adopted.before_revision || adopted.revision.seq > 1">{{ T('reorder.adoptedKeep', { n: adopted.before_revision?.seq ?? adopted.revision.seq - 1 }) }}</span></div>
      <button class="btn btn-sm" type="button" data-testid="cp-adopted-revisions" @click="emit('revisions')">{{ T('view.revisions') }}</button>
      <button v-if="adopted.revision.seq > 1" class="btn btn-sm" type="button" data-testid="cp-adopted-diff" @click="diffAdopted">{{ T('viewDiff') }}</button>
      <button class="btn btn-sm btn-primary" type="button" @click="emit('back')">{{ T('backWs') }}</button>
    </div>

    <div v-if="err" class="notice err"><Icon name="err" /><div class="grow">{{ err }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
    <section v-else-if="!res" class="panel"><div class="empty">{{ $t('c.loading') }}</div></section>
    <template v-else>
      <div v-if="!res.changed && !adopted" class="notice info" data-testid="cp-reorder-none"><Icon name="info" /><div>{{ T('reorder.none') }}</div></div>
      <div v-for="(w, i) in res.warnings" :key="i" class="notice warn"><Icon name="warn" /><div>{{ warnText(w) }}</div></div>
      <div class="sumline">
        <span class="mvn"><Icon name="move" /><span data-testid="cp-reorder-n">{{ T('reorder.moving', { n: res.moves.length }) }}</span></span>
        <span>{{ T('reorder.keep', { n: Math.max(0, cols.before.length - res.moves.length) }) }}</span>
        <span>{{ dirty && !adopted ? T('reorder.basedDraft') : T('reorder.basedRev', { n: script.revisions }) }} · {{ T('reorder.orderErrors') }} <b style="color: var(--red-ink)">{{ res.before.order_violations }}</b> → <b style="color: var(--teal-ink)">{{ res.after.order_violations }}</b></span>
      </div>

      <div class="ro-wrap">
        <section class="panel" style="overflow: hidden">
          <div class="ro2" data-testid="cp-reorder-cols" @mouseleave="hot = -1">
            <div class="codep">
              <div class="pane-h"><span>{{ T('reorder.before') }}</span><span class="faint">{{ T('linesN', { n: cols.before.length }) }}</span></div>
              <div>
                <div v-for="l in cols.before" :key="l.no" class="rl" :class="{ 'is-mv': l.moveIdx !== null, 'is-hot': l.moveIdx !== null && l.moveIdx === hot, 'k-dim': DIM.test(l.text) }" @mouseenter="hot = l.moveIdx ?? -1">
                  <span class="no">{{ l.no }}</span><span class="tx code-t">{{ l.text }}</span><span class="tg">{{ l.tag }}</span>
                </div>
              </div>
            </div>
            <div class="ro-wires">
              <div class="pane-h"><Icon name="move" small /></div>
              <svg :viewBox="`0 0 ${WIRE_W} ${svgH}`" :style="{ height: `${svgH}px` }" preserveAspectRatio="none" aria-hidden="true">
                <template v-for="w in wires" :key="w.i">
                  <path :class="hot < 0 ? '' : w.i === hot ? 'is-hot' : 'is-dim'" :d="w.d" />
                  <circle cx="2" :cy="w.y1" r="3" /><circle :cx="WIRE_W - 2" :cy="w.y2" r="3" />
                </template>
              </svg>
            </div>
            <div class="codep">
              <div class="pane-h"><span>{{ T('reorder.after') }}</span><span class="faint">{{ adopted ? T('reorder.savedAs', { n: adopted.revision?.seq ?? '' }) : T('reorder.unsaved') }}</span></div>
              <div>
                <div v-for="l in cols.after" :key="l.no" class="rl" :class="{ 'is-mv': l.moveIdx !== null, 'is-hot': l.moveIdx !== null && l.moveIdx === hot, 'k-dim': DIM.test(l.text) }" @mouseenter="hot = l.moveIdx ?? -1">
                  <span class="no">{{ l.no }}</span><span class="tx code-t">{{ l.text }}</span><span class="tg">{{ l.tag }}</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section class="panel whyp">
          <div class="panel-h"><h3>{{ T('reorder.why') }}</h3></div>
          <div class="why-l" data-testid="cp-reorder-why">
            <div v-if="!res.moves.length" class="small faint" style="padding: 12px 14px">{{ T('none') }}</div>
            <div v-for="(m, i) in res.moves" :key="i" class="why-i" :class="{ 'is-hot': i === hot }" tabindex="0" @mouseenter="hot = i" @focusin="hot = i">
              <div class="hd"><span class="mvx" data-testid="cp-move">{{ T('reorder.lineMove', { a: m.line, b: m.new_line }) }}</span></div>
              <code>{{ m.text.trim() }}</code>
              <div v-for="(r, k) in m.reasons" :key="k">
                <div class="rs-t">{{ r.text }}</div>
                <div class="dep"><i :style="{ background: KIND_COLOR[r.kind] || 'var(--ink-3)' }" />{{ T('reorder.depKind') }}{{ T(`reason.${r.kind}`) }}</div>
              </div>
            </div>
          </div>
          <ol class="principles">
            <li>{{ T('reorder.p1') }}</li><li>{{ T('reorder.p2') }}</li><li>{{ T('reorder.p3') }}</li><li>{{ T('reorder.p4') }}</li>
          </ol>
        </section>
      </div>

      <section class="panel" style="margin-top: 10px">
        <div class="ro-foot">
          <div class="res">
            <span class="big" :style="res.after.order_violations ? 'color: var(--red-ink)' : ''"><Icon :name="res.after.order_violations ? 'warn' : 'ok'" /><span data-testid="cp-reorder-after">{{ T('reorder.afterCheck', { n: res.after.order_violations }) }}</span></span>
            <span class="muted">{{ T('reorder.remain') }}</span>
            <span class="cnt">
              <span :class="res.after.summary.errors ? 'e' : 'zero'"><span class="sevdot" :class="res.after.summary.errors ? 'error' : ''" /><b>{{ res.after.summary.errors }}</b></span>
              <span :class="res.after.summary.warnings ? 'w' : 'zero'"><span class="sevdot" :class="res.after.summary.warnings ? 'warning' : ''" /><b>{{ res.after.summary.warnings }}</b></span>
              <span :class="res.after.summary.infos ? 'i' : 'zero'"><span class="sevdot" :class="res.after.summary.infos ? 'info' : ''" /><b>{{ res.after.summary.infos }}</b></span>
            </span>
          </div>
          <span style="flex: 1" />
          <button class="btn" type="button" @click="emit('back')">{{ adopted ? T('backWs') : $t('c.cancel') }}</button>
          <button v-if="!adopted" class="btn btn-primary" type="button" :disabled="busy || !res.changed" data-testid="cp-adopt" @click="adopt"><Icon name="check" small /><span>{{ T('reorder.adopt') }}</span></button>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.ro-wrap { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 10px; align-items: start; }
.ro2 { display: grid; grid-template-columns: minmax(0, 1fr) 72px minmax(0, 1fr); }
.ro2 > .ro-wires { border-left: 1px solid var(--line); border-right: 1px solid var(--line); background: var(--surface-2); position: relative; }
.ro2 .pane-h { display: flex; align-items: center; gap: 8px; padding: 0 12px; border-bottom: 1px solid var(--line); font-size: 12.5px; font-weight: 600; height: 40px; white-space: nowrap; overflow: hidden; box-sizing: border-box; }
.ro2 .pane-h .faint { font-weight: 400; font-size: 12px; }
.ro-wires .pane-h { padding: 0; justify-content: center; color: var(--mv-ink); }
.ro-wires > svg { position: absolute; left: 0; top: 0; width: 100%; overflow: visible; }
.sumline { display: flex; gap: 8px 18px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; font-size: 12.5px; color: var(--ink-2); }
.sumline b { color: var(--ink); }
.sumline .mvn { font: 600 15px var(--font-display); color: var(--mv-ink); display: inline-flex; align-items: center; gap: 6px; }
.principles { margin: 0; padding: 10px 14px 12px 30px; font-size: 12px; color: var(--ink-2); line-height: 1.7; border-top: 1px solid var(--line); }
.adopted, .notice { margin-bottom: 10px; }
.cnt .sevdot:not(.error):not(.warning):not(.info) { background: var(--line-strong); }
@media (max-width: 1240px) { .ro-wrap { grid-template-columns: minmax(0, 1fr); } }
</style>
