<script setup lang="ts">
/** 修订记录（预览 REQ-031/revisions.html）：时间线、来源、作者、问题计数、预览、恢复（形成新修订）、选两条对比。 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText, get, post } from '@/api'
import { useProject } from '@/stores/project'
import { fmtTime, orderPicks, revFrom, revMoves, splitLines, summaryCounts, togglePick } from './logic'
import type { Revision, ScriptInfo } from './types'

const proj = useProject() // 只读成员不能采纳重排、恢复修订（REQ-036）
const props = defineProps<{ pid: number; script: ScriptInfo; scripts: ScriptInfo[] }>()
const emit = defineEmits<{
  (e: 'switch', id: number): void
  (e: 'restored', content: string, s: ScriptInfo | null): void
  (e: 'diff', a: string, b: string): void
  (e: 'back'): void
}>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`check-projects.${k}`, p ?? {})

const SRC_ICON: Record<string, string> = { manual: 'check', reorder: 'order', restore: 'rollback', create: 'plus' }
const revs = ref<Revision[] | null>(null)
const err = ref('')
const sel = ref<number | null>(null)
const picks = ref<number[]>([])
const contents = ref<Record<number, string>>({})
const pvErr = ref('')
const confirmRes = ref(false)
const busy = ref(false)
const toast = ref('')

const base = () => `/check-projects/${props.pid}/scripts/${props.script.id}`
const current = computed(() => revs.value?.[0] ?? null)
const selRev = computed(() => revs.value?.find((r) => r.id === sel.value) ?? null)
const pair = computed(() => (revs.value ? orderPicks(picks.value, revs.value) : null))
const pvLines = computed(() => (sel.value !== null && contents.value[sel.value] !== undefined ? splitLines(contents.value[sel.value]) : null))

async function load(keepSel = false): Promise<void> {
  err.value = ''
  try {
    revs.value = (await get<{ revisions: Revision[] }>(`${base()}/revisions`)).revisions
    if (!keepSel || !revs.value.some((r) => r.id === sel.value)) sel.value = revs.value[0]?.id ?? null
    if (picks.value.length === 0 && revs.value.length >= 2) picks.value = [revs.value[1].id, revs.value[0].id]
  } catch (e) { err.value = errorText(e) }
}
watch(sel, async (id) => {
  pvErr.value = ''
  if (id === null || contents.value[id] !== undefined) return
  try {
    const r = await get<Revision>(`${base()}/revisions/${id}`)
    contents.value = { ...contents.value, [id]: r.content ?? '' }
  } catch (e) { pvErr.value = errorText(e) }
})
watch(() => props.script.id, () => { revs.value = null; picks.value = []; contents.value = {}; void load() })

function note(r: Revision): string {
  if (r.source === 'reorder') return T('rev.noteReorder', { n: revMoves(r), from: revFrom(r) ?? '—' })
  if (r.source === 'restore') return T('rev.noteRestore', { from: revFrom(r) ?? '—' })
  if (r.source === 'create') return T('rev.noteCreate')
  if (typeof r.note === 'string' && r.note) return r.note
  return T('rev.noteManual')
}

async function restore(): Promise<void> {
  const r = selRev.value
  if (!r) return
  busy.value = true
  try {
    const s = await post<ScriptInfo & { revision: Revision }>(`${base()}/revisions/${r.id}/restore`, {})
    confirmRes.value = false
    toast.value = T('rev.restored', { n: s.revision.seq })
    window.setTimeout(() => { toast.value = '' }, 2600)
    const { revision: _r, ...info } = s
    void _r
    emit('restored', s.content ?? '', { ...info, content: undefined })
    await load()
    sel.value = s.revision.id
    picks.value = [r.id, s.revision.id]
  } catch (e) { err.value = errorText(e) } finally { busy.value = false }
}
onMounted(() => load())
</script>

<template>
  <div data-testid="cp-revisions-pane">
    <div class="ph">
      <div class="ph-text">
        <h1>{{ T('rev.title') }}</h1>
        <p class="ph-sub">{{ T('rev.sub') }}</p>
      </div>
      <div class="ph-actions">
        <label class="small muted" for="scSel">{{ T('script') }}</label>
        <select id="scSel" class="select mono" style="width: 220px" :value="script.id" @change="emit('switch', Number(($event.target as HTMLSelectElement).value))">
          <option v-for="s in scripts" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
        <button class="btn" type="button" @click="emit('back')"><Icon name="chevL" small />{{ T('backWs') }}</button>
      </div>
    </div>

    <div v-if="err" class="notice err"><Icon name="err" /><div class="grow">{{ err }}</div><button class="btn btn-sm" type="button" @click="load()">{{ $t('c.retry') }}</button></div>
    <section v-else-if="!revs" class="panel"><div class="empty">{{ $t('c.loading') }}</div></section>
    <div v-else class="rvw">
      <section class="panel">
        <div class="panel-h">
          <h3>{{ T('rev.timeline') }} <span class="faint">{{ revs.length }}</span></h3>
          <span class="mini-legend"><span><span class="src manual">{{ T('src.manual') }}</span></span><span><span class="src reorder">{{ T('src.reorder') }}</span></span><span><span class="src restore">{{ T('src.restore') }}</span></span></span>
        </div>
        <div class="sb">
          <div class="tl" data-testid="cp-timeline">
            <div v-for="r in revs" :key="r.id" class="tli" :class="{ 'is-sel': r.id === sel }" :data-testid="`cp-rev-${r.seq}`" @click="sel = r.id">
              <span class="pick"><input type="checkbox" :checked="picks.includes(r.id)" :aria-label="`${T('rev.pick')} #${r.seq}`" @click.stop="picks = togglePick(picks, r.id)"></span>
              <span class="rail"><i :class="`s-${r.source}`" /></span>
              <div class="card">
                <div class="hd">
                  <span class="rn">#{{ r.seq }}</span>
                  <span class="src" :class="r.source"><Icon :name="SRC_ICON[r.source] || 'check'" />{{ T(`src.${r.source}`) }}</span>
                  <span v-if="r.id === current?.id" class="tag t-blue">{{ T('rev.current') }}</span>
                  <span class="tm" style="margin-left: auto">{{ fmtTime(r.created_at) }}</span>
                </div>
                <div class="nt">{{ note(r) }}</div>
                <div class="mt">
                  <span class="owner"><i>{{ (r.author || '?').charAt(0).toUpperCase() }}</i>{{ r.author }}</span>
                  <span>{{ T('linesN', { n: r.lines }) }}</span>
                  <span v-if="summaryCounts(r.summary)" class="cnt">
                    <span :class="r.summary!.errors ? 'e' : 'zero'"><span class="sevdot" :class="r.summary!.errors ? 'error' : 'none'" /><b>{{ r.summary!.errors }}</b></span>
                    <span :class="r.summary!.warnings ? 'w' : 'zero'"><span class="sevdot" :class="r.summary!.warnings ? 'warning' : 'none'" /><b>{{ r.summary!.warnings }}</b></span>
                    <span :class="r.summary!.infos ? 'i' : 'zero'"><span class="sevdot" :class="r.summary!.infos ? 'info' : 'none'" /><b>{{ r.summary!.infos }}</b></span>
                  </span>
                  <span v-else class="faint">{{ T('rev.noSummary') }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="cmpbar">
          <span>{{ T('compare') }}</span>
          <span class="slot" :class="{ on: pair }">{{ pair ? `#${pair[0].seq}` : T('rev.none') }} <small v-if="pair">{{ T('rev.older') }}</small></span>
          <span class="faint">↔</span>
          <span class="slot" :class="{ on: pair }">{{ pair ? `#${pair[1].seq}` : T('rev.none') }} <small v-if="pair">{{ T('rev.newer') }}</small></span>
          <span style="flex: 1" />
          <button class="btn btn-sm btn-primary" type="button" :disabled="!pair" data-testid="cp-rev-compare" @click="pair && emit('diff', `rev:${pair[0].id}`, `rev:${pair[1].id}`)"><Icon name="compare" small /><span>{{ T('rev.compareSel') }}</span></button>
        </div>
      </section>

      <section class="panel">
        <div v-if="selRev" class="panel-h pv-h">
          <span class="rn">#{{ selRev.seq }}</span>
          <span class="src" :class="selRev.source"><Icon :name="SRC_ICON[selRev.source] || 'check'" />{{ T(`src.${selRev.source}`) }}</span>
          <span class="small faint">{{ fmtTime(selRev.created_at) }} · {{ selRev.author }}</span>
          <span style="flex: 1" />
          <button v-if="selRev.id !== current?.id" class="btn btn-sm" type="button" @click="emit('diff', `rev:${selRev.id}`, `script:${script.id}`)"><Icon name="compare" small />{{ T('rev.vsCurrent') }}</button>
          <button v-if="proj.canWrite" class="btn btn-sm" type="button" :disabled="selRev.id === current?.id" :title="selRev.id === current?.id ? T('rev.isCurrent') : ''" data-testid="cp-rev-restore" @click="confirmRes = true"><Icon name="rollback" small />{{ T('rev.restore') }}</button>
        </div>
        <div class="sb">
          <div v-if="pvErr" class="notice err" style="margin: 10px"><Icon name="err" /><div>{{ pvErr }}</div></div>
          <div v-else-if="!pvLines" class="small faint" style="padding: 12px">{{ $t('c.loading') }}</div>
          <div v-else class="pvcode" data-testid="cp-rev-preview">
            <div v-for="(l, i) in pvLines" :key="i" class="pl"><span class="no">{{ i + 1 }}</span><span class="tx code-t">{{ l }}</span></div>
          </div>
        </div>
      </section>
    </div>

    <div v-if="confirmRes && selRev" class="modal-back" @click.self="confirmRes = false" @keydown.esc="confirmRes = false">
      <div class="modal sm" role="dialog" aria-modal="true" aria-labelledby="mResT">
        <div class="modal-h"><h2 id="mResT">{{ T('rev.restoreTitle', { n: selRev.seq }) }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="confirmRes = false"><Icon name="x" /></button></div>
        <div class="modal-b" style="display: flex; flex-direction: column; gap: 10px">
          <p>{{ T('rev.restoreMsg', { n: selRev.seq, next: (current?.seq ?? 0) + 1 }) }}</p>
          <div class="notice info"><Icon name="info" /><div>{{ T('rev.restoreNote') }}</div></div>
        </div>
        <div class="modal-f"><button class="btn" type="button" @click="confirmRes = false">{{ $t('c.cancel') }}</button><button class="btn btn-primary" type="button" :disabled="busy" data-testid="cp-rev-restore-ok" @click="restore">{{ T('rev.restoreAs', { n: (current?.seq ?? 0) + 1 }) }}</button></div>
      </div>
    </div>
    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </div>
</template>

<style scoped>
.rvw { height: max(520px, calc(100vh - var(--top-h) - 190px)); }
.rvw > .panel { display: flex; flex-direction: column; min-height: 0; }
.rvw .sb { flex: 1; overflow: auto; min-height: 0; }
.pv-h { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pv-h .rn { font: 700 14px var(--font-mono); }
.pvcode { font: 12.5px/22px var(--font-mono); background: var(--ed-bg); min-height: 100%; }
.pl { display: grid; grid-template-columns: 44px minmax(0, 1fr); }
.pl .no { text-align: right; padding-right: 8px; color: var(--ink-3); background: var(--ed-gutter); border-right: 1px solid var(--line); font-size: 11px; user-select: none; }
.pl .tx { white-space: pre; padding-left: 10px; color: var(--ink); }
.modal.sm { width: min(500px, 100%); }
.sevdot.none { background: var(--line-strong); }
</style>
