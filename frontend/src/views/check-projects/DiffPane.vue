<script setup lang="ts">
/**
 * 文本差异对比（预览 REQ-031/diff.html）：A / B 各选修订、项目内脚本或基线配置；并排 / 上下两种视图，行内字符标记，
 * 移动标紫（第 a 行 → 第 b 行），忽略顺序只看内容差异，语义差异（按有效值）；下载 .diff 与中 / 英 HTML 报告。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText, get, post } from '@/api'
import { usePrefs } from '@/stores/prefs'
import { useTerms } from '@/stores/terms'
import { postFile, saveBlob } from '@/views/check/report'
import { charSegments, fmtTime, foldEqual, reportLang, semValue, unifiedRows, type UniRow } from './logic'
import type { DiffResult, DiffRow, DiffSide, Project, Revision, ScriptInfo } from './types'

const props = defineProps<{ project: Project; scripts: ScriptInfo[]; cur: number | null; draft: string | null; initA: string; initB: string }>()
const emit = defineEmits<{ (e: 'back'): void }>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`check-projects.${k}`, p ?? {})
const prefs = usePrefs()
const terms = useTerms()

type SType = 'revision' | 'script' | 'baseline'
interface Side { type: SType; scriptId: number | null; revId: number | null; revSeq: number | null }
const hasBase = computed(() => props.project.device_id !== null)
const revs = reactive<Record<number, Revision[]>>({})

function parse(spec: string, fallback: Side): Side {
  const [k, x, y] = spec.split(':')
  if (k === 'base' && hasBase.value) return { type: 'baseline', scriptId: null, revId: null, revSeq: null }
  if (k === 'script' && x) return { type: 'script', scriptId: Number(x), revId: null, revSeq: null }
  if (k === 'rev' && x) return { type: 'revision', scriptId: null, revId: Number(x), revSeq: null }
  if (k === 'revseq' && x && y) return { type: 'revision', scriptId: Number(x), revId: null, revSeq: Number(y) }
  return fallback
}
const curScript = computed(() => props.scripts.find((s) => s.id === props.cur) ?? props.scripts[0] ?? null)
function defaults(): [Side, Side] {
  const s = curScript.value
  const b: Side = s ? { type: 'script', scriptId: s.id, revId: null, revSeq: null } : { type: 'baseline', scriptId: null, revId: null, revSeq: null }
  let a: Side
  if (s && (props.draft !== null ? s.revisions >= 1 : s.revisions >= 2)) a = { type: 'revision', scriptId: s.id, revId: null, revSeq: props.draft !== null ? s.revisions : s.revisions - 1 }
  else if (hasBase.value) a = { type: 'baseline', scriptId: null, revId: null, revSeq: null }
  else a = { ...b }
  return [a, b]
}
const [da, db] = defaults()
const A = ref<Side>(parse(props.initA, da))
const B = ref<Side>(parse(props.initB, db))

async function loadRevs(sid: number): Promise<Revision[]> {
  if (!revs[sid]) {
    try { revs[sid] = (await get<{ revisions: Revision[] }>(`/check-projects/${props.project.id}/scripts/${sid}/revisions`)).revisions } catch { revs[sid] = [] }
  }
  return revs[sid]
}
/** 修订一侧只知道修订编号时，找出它属于哪份脚本；只知道序号时找出编号。 */
async function resolve(s: Side): Promise<void> {
  if (s.type !== 'revision') return
  if (s.scriptId === null && s.revId !== null) {
    for (const sc of props.scripts) {
      const rs = await loadRevs(sc.id)
      if (rs.some((r) => r.id === s.revId)) { s.scriptId = sc.id; break }
    }
  }
  if (s.scriptId === null) s.scriptId = curScript.value?.id ?? null
  if (s.scriptId === null) return
  const rs = await loadRevs(s.scriptId)
  if (s.revId === null) s.revId = (rs.find((r) => r.seq === s.revSeq) ?? rs[0])?.id ?? null
}

function body(s: Side): DiffSide | null {
  if (s.type === 'baseline') return { type: 'baseline', project_id: props.project.id }
  if (s.type === 'script' && s.scriptId !== null) {
    return s.scriptId === props.cur && props.draft !== null ? { type: 'script', script_id: s.scriptId, text: props.draft } : { type: 'script', script_id: s.scriptId }
  }
  if (s.type === 'revision' && s.revId !== null) return { type: 'revision', revision_id: s.revId }
  return null
}
function sideName(s: Side): string {
  if (s.type === 'baseline') return props.project.device?.name ?? T('baseline')
  const sc = props.scripts.find((x) => x.id === s.scriptId)
  if (s.type === 'script') return `${sc?.name ?? ''}${s.scriptId === props.cur && props.draft !== null ? T('diff.inEditor') : ''}`
  const r = s.scriptId !== null ? revs[s.scriptId]?.find((x) => x.id === s.revId) : null
  return `${sc?.name ?? ''} #${r?.seq ?? ''}`
}

const ignore = ref(false)
const tab = ref<'text' | 'sem'>('text')
const mode = ref<'split' | 'unified'>('split')
const showAll = ref(false)
const res = ref<DiffResult | null>(null)
const err = ref('')
const loading = ref(false)
let seq = 0

const reqBody = computed(() => {
  const a = body(A.value)
  const b = body(B.value)
  return a && b ? { a, b, ignore_order: ignore.value, semantic: true, style: terms.style } : null
})
async function run(): Promise<void> {
  await resolve(A.value)
  await resolve(B.value)
  const rb = reqBody.value
  if (!rb) return
  const k = ++seq
  loading.value = true
  err.value = ''
  try {
    const r = await post<DiffResult>('/check-projects/diff', rb)
    if (k === seq) res.value = r
  } catch (e) { if (k === seq) err.value = errorText(e) } finally { if (k === seq) loading.value = false }
}
watch([A, B, ignore, () => terms.style], () => { void run() }, { deep: true })

function setType(side: 'A' | 'B', type: SType): void {
  const s = curScript.value
  const v: Side = type === 'baseline' ? { type, scriptId: null, revId: null, revSeq: null }
    : type === 'script' ? { type, scriptId: s?.id ?? null, revId: null, revSeq: null }
      : { type, scriptId: s?.id ?? null, revId: null, revSeq: null }
  if (side === 'A') A.value = v
  else B.value = v
}
function setScript(side: 'A' | 'B', id: number): void {
  const s = side === 'A' ? A.value : B.value
  const v: Side = { ...s, scriptId: id, revId: null, revSeq: null }
  if (side === 'A') A.value = v
  else B.value = v
}
function setRev(side: 'A' | 'B', id: number): void {
  const s = side === 'A' ? A.value : B.value
  const v: Side = { ...s, revId: id }
  if (side === 'A') A.value = v
  else B.value = v
}
function swap(): void { const x = A.value; A.value = B.value; B.value = x }

/* 视图 */
type SplitItem = DiffRow | { fold: number }
type UniItem = UniRow | { fold: number }
const splitRows = computed<SplitItem[]>(() => (res.value ? (showAll.value ? res.value.rows : foldEqual(res.value.rows)) : []))
const uniRows = computed<UniItem[]>(() => {
  const u = res.value ? unifiedRows(res.value.rows) : []
  return showAll.value ? u : foldEqual(u)
})
const isFold = (x: object): x is { fold: number } => 'fold' in x
const DK: Record<string, string> = { added: 'added', removed: 'removed', changed: 'modified', renamed: 'renamed' }

/* 下载 */
const dlErr = ref('')
async function download(format: 'unified' | 'html', lang?: 'zh-CN' | 'en'): Promise<void> {
  const rb = reqBody.value
  if (!rb) return
  dlErr.value = ''
  const rl = lang ?? reportLang(prefs.lang)
  try {
    const f = await postFile('/check-projects/diff/report', { ...rb, format, report_lang: rl }, format === 'unified' ? 'diff.diff' : `diff.${rl}.html`)
    saveBlob(f.blob, f.name)
  } catch (e) { dlErr.value = errorText(e) }
}

onMounted(async () => {
  for (const s of props.scripts.filter((x) => x.id === props.cur)) await loadRevs(s.id)
  await run()
})
</script>

<template>
  <div data-testid="cp-diff-pane">
    <div class="ph">
      <div class="ph-text">
        <h1>{{ T('view.diff') }}</h1>
        <p class="ph-sub">{{ T('diff.sub') }}</p>
      </div>
      <div class="ph-actions"><button class="btn" type="button" @click="emit('back')"><Icon name="chevL" small />{{ T('backWs') }}</button></div>
    </div>

    <section class="panel">
      <div class="panel-b">
        <div class="dsel">
          <div v-for="side in (['A', 'B'] as const)" :key="side" class="dside" :data-testid="`cp-diff-side-${side}`" :style="{ order: side === 'A' ? 0 : 2 }">
            <div class="hd"><span class="sb-l" :class="{ b: side === 'B' }">{{ side }}</span><span>{{ side === 'A' ? T('diff.sideA') : T('diff.sideB') }}</span></div>
            <div class="seg" role="group">
              <button type="button" :aria-pressed="(side === 'A' ? A : B).type === 'revision'" @click="setType(side, 'revision')">{{ T('diff.typeRev') }}</button>
              <button type="button" :aria-pressed="(side === 'A' ? A : B).type === 'script'" @click="setType(side, 'script')">{{ T('diff.typeScript') }}</button>
              <button type="button" :aria-pressed="(side === 'A' ? A : B).type === 'baseline'" :disabled="!hasBase" @click="setType(side, 'baseline')">{{ T('diff.typeBase') }}</button>
            </div>
            <div v-if="(side === 'A' ? A : B).type !== 'baseline'" class="pick2">
              <select class="select" :value="(side === 'A' ? A : B).scriptId ?? ''" :aria-label="T('script')" @change="setScript(side, Number(($event.target as HTMLSelectElement).value))">
                <option v-for="s in scripts" :key="s.id" :value="s.id">{{ s.name }}</option>
              </select>
              <select v-if="(side === 'A' ? A : B).type === 'revision'" class="select" :value="(side === 'A' ? A : B).revId ?? ''" :aria-label="T('diff.typeRev')" :data-testid="`cp-diff-rev-${side}`" @change="setRev(side, Number(($event.target as HTMLSelectElement).value))">
                <option v-for="(r, i) in revs[(side === 'A' ? A : B).scriptId ?? -1] ?? []" :key="r.id" :value="r.id">#{{ r.seq }} · {{ fmtTime(r.created_at) }} · {{ T(`src.${r.source}`) }}{{ i === 0 ? T('diff.currentSuffix') : '' }}</option>
              </select>
            </div>
            <div class="meta mono">{{ sideName(side === 'A' ? A : B) }}</div>
          </div>
          <div class="dswap" style="order: 1"><button class="btn btn-icon" type="button" :title="T('diff.swap')" :aria-label="T('diff.swap')" data-testid="cp-diff-swap" @click="swap"><Icon name="swap" /></button></div>
        </div>
      </div>
    </section>

    <div v-if="err" class="notice err" style="margin-top: 10px"><Icon name="err" /><div class="grow">{{ err }}</div><button class="btn btn-sm" type="button" @click="run">{{ $t('c.retry') }}</button></div>
    <template v-else-if="res">
      <div class="dstat" style="margin-top: 10px" data-testid="cp-diff-stats">
        <div><span class="n add">{{ res.stats.add }}</span><span class="k"><span class="dk added">{{ T('dk.added') }}</span>{{ T('diff.lines') }}</span></div>
        <div><span class="n del">{{ res.stats.del }}</span><span class="k"><span class="dk removed">{{ T('dk.removed') }}</span>{{ T('diff.lines') }}</span></div>
        <div><span class="n mod">{{ res.stats.change }}</span><span class="k"><span class="dk modified">{{ T('dk.changed') }}</span>{{ T('diff.lines') }}</span></div>
        <div><span class="n mv" data-testid="cp-diff-moves">{{ ignore ? '—' : res.stats.move }}</span><span class="k"><span class="dk moved">{{ T('diff.moved') }}</span>{{ ignore ? T('diff.ignored') : T('diff.lines') }}</span></div>
        <div class="opts"><span class="small muted">A：<span class="mono">{{ res.a.label }}</span></span><span class="small muted">B：<span class="mono">{{ res.b.label }}</span></span></div>
      </div>

      <div class="dtool">
        <div class="tabs" role="tablist">
          <button role="tab" type="button" :aria-selected="tab === 'text'" data-testid="cp-diff-tab-text" @click="tab = 'text'">{{ T('diff.tabText') }}</button>
          <button role="tab" type="button" :aria-selected="tab === 'sem'" data-testid="cp-diff-tab-sem" @click="tab = 'sem'">{{ T('diff.tabSem') }}</button>
        </div>
        <div v-show="tab === 'text'" class="seg" role="group" data-testid="cp-diff-mode">
          <button type="button" :aria-pressed="mode === 'split'" @click="mode = 'split'"><Icon name="compare" small /><span>{{ T('diff.split') }}</span></button>
          <button type="button" :aria-pressed="mode === 'unified'" data-mode="unified" @click="mode = 'unified'"><Icon name="rows" small /><span>{{ T('diff.unified') }}</span></button>
        </div>
        <label v-show="tab === 'text'" class="check"><span class="switch"><input v-model="ignore" type="checkbox" data-testid="cp-diff-ignore"><span /></span><span>{{ T('diff.ignore') }}</span></label>
        <label v-show="tab === 'text' && !ignore" class="check"><input v-model="showAll" type="checkbox"><span>{{ T('diff.showAll') }}</span></label>
        <span class="grow" />
        <span class="dl">
          <span class="k">{{ T('diff.download') }}</span>
          <button class="btn btn-sm" type="button" data-testid="cp-dl-diff" @click="download('unified')"><Icon name="download" small />.diff</button>
          <button class="btn btn-sm" type="button" data-testid="cp-dl-zh" @click="download('html', 'zh-CN')"><Icon name="report" small /><span>{{ T('diff.reportZh') }}</span></button>
          <button class="btn btn-sm" type="button" data-testid="cp-dl-en" @click="download('html', 'en')"><Icon name="report" small /><span>{{ T('diff.reportEn') }}</span></button>
        </span>
      </div>
      <div v-if="dlErr" class="notice err" style="margin-bottom: 8px"><Icon name="err" /><div>{{ dlErr }}</div></div>

      <section class="panel" style="overflow: hidden" :class="{ 'is-loading': loading }" data-testid="cp-diff-out">
        <template v-if="tab === 'text'">
          <template v-if="ignore && res.unordered">
            <div class="ign-note"><Icon name="move" small />{{ T('diff.ignoreNote') }}</div>
            <div v-if="res.unordered.equal" class="empty" data-testid="cp-diff-unordered-equal"><Icon name="ok" /><h3>{{ T('diff.unorderedEqual') }}</h3></div>
            <div v-else class="uo">
              <div v-for="side in (['a', 'b'] as const)" :key="side" class="uo-col">
                <div class="uo-h"><span class="dk" :class="side === 'a' ? 'removed' : 'added'">{{ side === 'a' ? T('diff.onlyA') : T('diff.onlyB') }}</span> <span class="faint">{{ (side === 'a' ? res.unordered.only_a : res.unordered.only_b).length }}</span></div>
                <div v-for="(x, i) in side === 'a' ? res.unordered.only_a : res.unordered.only_b" :key="i" class="uo-i">
                  <span class="ln">{{ x.lines.slice(0, 3).join(', ') }}{{ x.lines.length > 3 ? '…' : '' }}</span><code>{{ x.text }}</code><span v-if="x.count > 1" class="faint">×{{ x.count }}</span>
                </div>
                <div v-if="!(side === 'a' ? res.unordered.only_a : res.unordered.only_b).length" class="small faint" style="padding: 8px 12px">{{ T('none') }}</div>
              </div>
            </div>
          </template>
          <div v-else-if="res.equal" class="empty"><Icon name="ok" /><h3>{{ T('diff.same') }}</h3></div>
          <template v-else-if="mode === 'split'">
            <div class="vhead"><div><span class="sbl a">A</span><code>{{ res.a.label }}</code></div><i /><div><span class="sbl b">B</span><code>{{ res.b.label }}</code></div></div>
            <div class="dvw" data-testid="cp-diff-split">
              <table>
                <colgroup><col style="width: 42px"><col style="width: 20px"><col><col style="width: 1px"><col style="width: 42px"><col style="width: 20px"><col></colgroup>
                <tbody>
                  <template v-for="(r, i) in splitRows" :key="i">
                    <tr v-if="isFold(r)" class="fold"><td colspan="7"><button type="button" class="btn btn-xs btn-ghost" @click="showAll = true">{{ T('diff.folded', { n: r.fold }) }}</button></td></tr>
                    <tr v-else :data-t="r.t">
                      <template v-if="r.t === 'equal'"><td class="n">{{ r.a }}</td><td class="m" /><td class="t">{{ r.at }}</td></template>
                      <template v-else-if="r.t === 'del'"><td class="n c-del">{{ r.a }}</td><td class="m c-del">−</td><td class="t c-del">{{ r.at }}</td></template>
                      <template v-else-if="r.t === 'change'"><td class="n c-mod">{{ r.a }}</td><td class="m c-mod">~</td><td class="t c-mod"><template v-for="(s, k) in charSegments(r.at, r.sa)" :key="k"><span v-if="s.hit" class="cx-d">{{ s.t }}</span><template v-else>{{ s.t }}</template></template></td></template>
                      <template v-else-if="r.t === 'move_from'"><td class="n c-mv">{{ r.a }}</td><td class="m c-mv">↕</td><td class="t c-mv">{{ r.at }}<span class="mvtag">{{ T('diff.movedTo', { n: r.to }) }}</span></td></template>
                      <template v-else><td class="n c-empty" /><td class="m c-empty" /><td class="t c-empty" /></template>
                      <td class="mid" />
                      <template v-if="r.t === 'equal'"><td class="n">{{ r.b }}</td><td class="m" /><td class="t">{{ r.bt }}</td></template>
                      <template v-else-if="r.t === 'add'"><td class="n c-add">{{ r.b }}</td><td class="m c-add">+</td><td class="t c-add">{{ r.bt }}</td></template>
                      <template v-else-if="r.t === 'change'"><td class="n c-mod">{{ r.b }}</td><td class="m c-mod">~</td><td class="t c-mod"><template v-for="(s, k) in charSegments(r.bt, r.sb)" :key="k"><span v-if="s.hit" class="cx-a">{{ s.t }}</span><template v-else>{{ s.t }}</template></template></td></template>
                      <template v-else-if="r.t === 'move_to'"><td class="n c-mv">{{ r.b }}</td><td class="m c-mv">↕</td><td class="t c-mv">{{ r.bt }}<span class="mvtag" data-testid="cp-mvtag">{{ T('diff.moveFromTo', { a: r.from, b: r.b }) }}</span></td></template>
                      <template v-else><td class="n c-empty" /><td class="m c-empty" /><td class="t c-empty" /></template>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>
          </template>
          <div v-else class="dvw" data-testid="cp-diff-unified">
            <table>
              <colgroup><col style="width: 42px"><col style="width: 42px"><col style="width: 20px"><col></colgroup>
              <tbody>
                <template v-for="(r, i) in uniRows" :key="i">
                  <tr v-if="isFold(r)" class="fold"><td colspan="4"><button type="button" class="btn btn-xs btn-ghost" @click="showAll = true">{{ T('diff.folded', { n: r.fold }) }}</button></td></tr>
                  <tr v-else-if="r.k === 'move-ghost'" class="ghost"><td class="n">{{ r.a }}</td><td class="n" /><td class="m" /><td class="t">↳ {{ T('diff.movedToLine', { n: r.to }) }}{{ r.text }}</td></tr>
                  <tr v-else>
                    <td class="n" :class="cls(r.k)">{{ r.a ?? '' }}</td><td class="n" :class="cls(r.k)">{{ r.b ?? '' }}</td>
                    <td class="m" :class="cls(r.k)">{{ r.k === 'del' || r.k === 'mod-del' ? '−' : r.k === 'add' || r.k === 'mod-add' ? '+' : r.k === 'move' ? '↕' : '' }}</td>
                    <td class="t" :class="cls(r.k)">
                      <template v-if="r.spans"><template v-for="(s, k) in charSegments(r.text, r.spans)" :key="k"><span v-if="s.hit" :class="r.k === 'mod-del' ? 'cx-d' : 'cx-a'">{{ s.t }}</span><template v-else>{{ s.t }}</template></template></template>
                      <template v-else>{{ r.text }}</template>
                      <span v-if="r.k === 'move'" class="mvtag">{{ T('diff.moveFromTo', { a: r.from, b: r.b }) }}</span>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
        </template>
        <template v-else>
          <div v-if="!res.semantic" class="panel-b"><div class="notice info"><Icon name="info" /><div>{{ T('diff.semNa') }}</div></div></div>
          <div v-else-if="res.semantic.equal" class="empty" data-testid="cp-sem-equal"><Icon name="ok" /><h3>{{ T('diff.semEqual') }}</h3></div>
          <div v-else class="sem" data-testid="cp-sem">
            <div v-for="(d, i) in res.semantic.diffs" :key="i" class="semo">
              <span><span class="dk" :class="DK[d.kind] || d.kind">{{ T(`dk.${d.kind}`) }}</span></span>
              <span class="obj">{{ d.label || terms.describe(d.node) }}</span>
              <div class="props">
                <span class="pk">{{ T('diff.value') }}</span>
                <span class="pv">
                  <template v-if="d.a && d.b"><span class="from">{{ semValue(d.a.value) }}</span><span class="ar">→</span><span class="to">{{ semValue(d.b.value) }}</span></template>
                  <span v-else-if="d.b" class="to">{{ semValue(d.b.value) }}</span>
                  <span v-else-if="d.a" class="from">{{ semValue(d.a.value) }}</span>
                  <span v-if="d.a?.lines?.length || d.b?.lines?.length" class="nt">{{ T('diff.semLines', { a: d.a?.lines?.join(',') || '—', b: d.b?.lines?.join(',') || '—' }) }}</span>
                </span>
              </div>
            </div>
          </div>
        </template>
      </section>
    </template>
    <section v-else class="panel" style="margin-top: 10px"><div class="empty">{{ $t('c.loading') }}</div></section>
  </div>
</template>

<script lang="ts">
const CLS: Record<string, string> = { del: 'c-del', add: 'c-add', 'mod-del': 'c-mod', 'mod-add': 'c-mod', move: 'c-mv', equal: '' }
function cls(k: string): string { return CLS[k] ?? '' }
</script>

<style scoped>
.panel-b { padding: 12px; }
.dside .select { font-family: var(--font-mono); font-size: 12px; }
.pick2 { display: flex; gap: 6px; flex-wrap: wrap; }
.pick2 .select { flex: 1; min-width: 140px; }
.dtool .grow { flex: 1; }
.dl { display: inline-flex; gap: 6px; align-items: center; }
.dl .k { font-size: 12px; color: var(--ink-3); }
.vhead { display: grid; grid-template-columns: minmax(0, 1fr) 1px minmax(0, 1fr); border-bottom: 1px solid var(--line); font-size: 12px; }
.vhead > div { padding: 7px 12px; display: flex; gap: 8px; align-items: center; min-width: 0; white-space: nowrap; overflow: hidden; }
.vhead > i { background: var(--line); }
.vhead code { overflow: hidden; text-overflow: ellipsis; }
.sbl { width: 18px; height: 18px; border-radius: 4px; display: inline-flex; align-items: center; justify-content: center; font: 700 10.5px var(--font-ui); border: 1.5px solid var(--red-line); color: var(--red-ink); flex: none; }
.sbl.b { border-color: var(--teal-line); color: var(--teal-ink); }
.ign-note { font-size: 12px; color: var(--ink-2); padding: 6px 12px; border-bottom: 1px solid var(--line); background: var(--surface-2); display: flex; gap: 6px; align-items: center; }
.ign-note .ico { color: var(--mv); }
tr.fold td { text-align: center; background: var(--surface-2); border-top: 1px dashed var(--line); border-bottom: 1px dashed var(--line); padding: 2px 0; font-family: var(--font-ui); }
.uo { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
.uo-col + .uo-col { border-left: 1px solid var(--line); }
.uo-h { padding: 8px 12px; border-bottom: 1px solid var(--line); font-size: 12px; }
.uo-i { display: grid; grid-template-columns: 64px minmax(0, 1fr) auto; gap: 8px; padding: 4px 12px; border-bottom: 1px solid var(--line); font-size: 12px; align-items: baseline; }
.uo-i .ln { color: var(--ink-3); font: 11px var(--font-mono); }
.uo-i code { overflow-wrap: anywhere; white-space: pre-wrap; }
.is-loading { opacity: .6; }
</style>
