<script setup lang="ts">
/**
 * 版本历史与对比：内置版本与每次保存的版本（来源 编辑 / 加入示例 / 进化批准）；勾选两个版本逐字段对比（统一 / 并排）。
 * 回滚、恢复内置只把“当前生效”指向所选版本，不新增版本记录，版本文件不删除。
 */
import { computed, onMounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { errorText, get, post } from '@/api'
import { shortTime } from '@/views/account/account'
import Bits from './Bits.vue'
import DiffList from './DiffList.vue'
import HlText from './HlText.vue'
import { useSkillCtx, useT } from './ctx'
import { orderPair, textFields } from './logic'
import type { Definition, DiffResult, VersionRow } from './types'

const { detail, reload, flash, goTab } = useSkillCtx()
const { T, vlabel } = useT()
const versions = ref<VersionRow[]>([])
const err = ref('')
const picks = ref<string[]>([])
const swap = ref(false)
const view = ref<'uni' | 'sbs'>('uni')
const diff = ref<DiffResult | null>(null)
const diffErr = ref('')
const confirm = ref<string | null>(null)
const busy = ref(false)
const viewing = ref<{ v: string; def: Definition | null; err: string } | null>(null)
const known = computed(() => (detail.value?.variables ?? []).map((v) => v.name))
const SRC_ICON: Record<string, string> = { builtin: 'lock', edit: 'pencil', example: 'plus', evolution: 'dna' }

async function load(): Promise<void> {
  if (!detail.value) return
  err.value = ''
  try {
    const r = await get<{ versions: VersionRow[] }>(`/ai/skills/${detail.value.id}/versions`)
    versions.value = r.versions
    if (!picks.value.length) {
      const ids = r.versions.map((v) => v.version)
      picks.value = ids.length >= 2 ? ids.slice(-2) : ids
    }
  } catch (e) { err.value = errorText(e) }
}
onMounted(load)

const list = computed(() => [...versions.value].reverse())
const pair = computed(() => orderPair(picks.value, swap.value))
watch(pair, async (p) => {
  diff.value = null
  diffErr.value = ''
  if (!p || !detail.value) return
  try { diff.value = await get<DiffResult>(`/ai/skills/${detail.value.id}/diff?a=${encodeURIComponent(p[0])}&b=${encodeURIComponent(p[1])}`) } catch (e) { diffErr.value = errorText(e) }
}, { immediate: true })

function togglePick(v: string, on: boolean): void {
  const p = picks.value.filter((x) => x !== v)
  if (on) p.push(v)
  picks.value = p.slice(-2)
  swap.value = false
}
function abOf(v: string): 'a' | 'b' | '' {
  const p = pair.value
  if (!p) return ''
  return p[0] === v ? 'a' : p[1] === v ? 'b' : ''
}
async function doConfirm(): Promise<void> {
  const v = confirm.value
  confirm.value = null
  if (v === null || !detail.value) return
  busy.value = true
  try {
    if (v === 'builtin') await post(`/ai/skills/${detail.value.id}/restore`)
    else await post(`/ai/skills/${detail.value.id}/rollback`, { version: v })
    await Promise.all([reload(false), load()])
    flash(T('ver.nowActive', { v: vlabel(v) }))
  } catch (e) { flash(errorText(e)) } finally { busy.value = false }
}
async function openView(v: string): Promise<void> {
  if (!detail.value) return
  viewing.value = { v, def: null, err: '' }
  try {
    const r = await get<{ definition: Definition }>(`/ai/skills/${detail.value.id}/versions/${encodeURIComponent(v)}`)
    if (viewing.value?.v === v) viewing.value = { v, def: r.definition, err: '' }
  } catch (e) { if (viewing.value) viewing.value.err = errorText(e) }
}
function exText(d: Definition): string {
  return d.examples.map((e, i) => `#${i + 1} input: ${e.input}\n   output: ${e.output}${e.note ? `\n   note: ${e.note}` : ''}`).join('\n') || '—'
}
</script>

<template>
  <div v-if="detail" data-testid="sk-versions">
    <div v-if="err" class="notice err"><Icon name="err" /><div class="grow">{{ err }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
    <p class="small muted" style="margin-bottom: 10px">{{ T('ver.intro') }}</p>
    <div class="vlayout">
      <section class="panel">
        <div class="panel-h"><h2>{{ T('ver.list') }}</h2><span class="meta">{{ T('ver.count', { n: versions.length }) }}</span></div>
        <div class="vtl" data-testid="ver-list">
          <div v-for="v in list" :key="v.version" class="vi" :class="[`s-${v.source}`, { 'is-cur': v.active, 'is-pick': picks.includes(v.version) }]" :data-version="v.version" data-testid="ver-item">
            <label class="pickc"><input type="checkbox" :checked="picks.includes(v.version)" :aria-label="T('ver.pick')" @change="togglePick(v.version, ($event.target as HTMLInputElement).checked)"></label>
            <span class="dot"><Icon :name="SRC_ICON[v.source] ?? 'pencil'" /></span>
            <div>
              <div class="vh">
                <span class="vn">{{ vlabel(v.version) }}</span><Bits kind="src" :s="v.source" />
                <span v-if="v.active" class="curmark" data-testid="ver-active">{{ T('ver.active') }}</span>
                <span v-if="abOf(v.version)" class="pickab" :class="abOf(v.version)">{{ abOf(v.version).toUpperCase() }}</span>
              </div>
              <div class="vmeta">
                <template v-if="v.source === 'builtin'">{{ T('ver.shipped') }}</template>
                <template v-else>{{ v.author || '—' }} · {{ shortTime(v.saved_at) }}<template v-if="v.based_on"> · {{ T('ver.basedOn', { v: vlabel(v.based_on) }) }}</template><template v-if="v.evolution"> · {{ T('ver.fromEvo', { n: v.evolution }) }}</template></template>
              </div>
              <div v-if="v.note" class="vnote">{{ v.note }}</div>
            </div>
            <div class="vops">
              <button class="btn btn-xs" type="button" data-testid="ver-view" @click="openView(v.version)"><Icon name="eye" small />{{ T('ver.view') }}</button>
              <template v-if="!v.active">
                <button v-if="v.version === 'builtin'" class="btn btn-xs" type="button" :disabled="busy" data-testid="ver-restore" @click="confirm = 'builtin'"><Icon name="rollback" small />{{ T('ver.restore') }}</button>
                <button v-else class="btn btn-xs" type="button" :disabled="busy" data-testid="ver-rollback" @click="confirm = v.version"><Icon name="rollback" small />{{ T('ver.rollback') }}</button>
              </template>
            </div>
          </div>
        </div>
        <div class="panel-f small faint">{{ T('ver.pickNote') }}</div>
      </section>
      <section class="panel" data-testid="ver-compare">
        <div class="panel-h cmp-h">
          <h2>{{ T('ver.compare') }}</h2>
          <span v-if="pair" class="ab"><span class="tagab a">A</span><b>{{ vlabel(pair[0]) }}</b><span class="faint">→</span><span class="tagab b">B</span><b>{{ vlabel(pair[1]) }}</b></span>
          <button class="btn btn-sm" type="button" :disabled="!pair" @click="swap = !swap"><Icon name="swap" small />{{ T('ver.swap') }}</button>
          <span style="flex: 1" />
          <div class="seg" role="group" data-testid="ver-view-mode">
            <button type="button" :aria-pressed="view === 'uni'" @click="view = 'uni'">{{ T('ver.unified') }}</button>
            <button type="button" :aria-pressed="view === 'sbs'" @click="view = 'sbs'">{{ T('ver.sbs') }}</button>
          </div>
        </div>
        <div class="panel-b">
          <div v-if="versions.length < 2" class="empty">
            <h3>{{ T('ver.onlyBuiltin') }}</h3><p>{{ T('ver.onlyBuiltinText') }}</p>
            <button class="btn btn-primary" type="button" @click="goTab('def')"><Icon name="pencil" small />{{ T('ver.goEdit') }}</button>
          </div>
          <div v-else-if="!pair" class="empty"><Icon name="compare" /><h3>{{ T('ver.pickTwo') }}</h3><p>{{ T('ver.pickTwoText') }}</p></div>
          <div v-else-if="diffErr" class="notice err"><Icon name="err" /><div>{{ diffErr }}</div></div>
          <div v-else-if="!diff" class="muted">{{ $t('c.loading') }}</div>
          <template v-else>
            <p class="small muted" style="margin-bottom: 10px" data-testid="ver-changed">{{ T('ver.changed', { n: diff.changed, all: diff.fields.length }) }}</p>
            <DiffList :fields="diff.fields" :known="known" :view="view" />
          </template>
        </div>
      </section>
    </div>

    <div v-if="confirm !== null" class="modal-back" @click.self="confirm = null">
      <div class="modal" role="dialog" aria-modal="true" style="width: min(560px, 100%)" data-testid="ver-confirm">
        <div class="modal-h"><h2>{{ confirm === 'builtin' ? T('ver.restoreTitle') : T('ver.rollbackTitle', { v: vlabel(confirm) }) }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="confirm = null"><Icon name="x" /></button></div>
        <div class="modal-b" style="display: flex; flex-direction: column; gap: 10px">
          <p>{{ confirm === 'builtin' ? T('ver.restoreText', { id: detail.id, cur: vlabel(detail.active) }) : T('ver.rollbackText', { id: detail.id, v: vlabel(confirm) }) }}</p>
          <div class="notice info"><Icon name="info" /><div class="grow small">{{ T('ver.keepNote') }}</div></div>
        </div>
        <div class="modal-f"><button class="btn" type="button" @click="confirm = null">{{ $t('c.cancel') }}</button><button class="btn btn-primary" type="button" data-testid="ver-confirm-ok" @click="doConfirm">{{ confirm === 'builtin' ? T('ver.restore') : T('ver.rollbackShort') }}</button></div>
      </div>
    </div>

    <div v-if="viewing" class="modal-back" @click.self="viewing = null">
      <div class="modal" role="dialog" aria-modal="true" style="width: min(820px, 100%)" data-testid="ver-view-dialog">
        <div class="modal-h"><h2>{{ detail.id }} · {{ vlabel(viewing.v) }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="viewing = null"><Icon name="x" /></button></div>
        <div class="modal-b vdef" style="max-height: 70vh; overflow: auto">
          <div v-if="viewing.err" class="notice err"><Icon name="err" /><div>{{ viewing.err }}</div></div>
          <div v-else-if="!viewing.def" class="muted">{{ $t('c.loading') }}</div>
          <template v-else>
            <div v-for="[f, text] in textFields(viewing.def)" :key="f" class="sent"><div class="sh"><b>{{ f }}</b></div><pre><HlText :text="text" :known="known" /></pre></div>
            <div class="sent"><div class="sh"><b>{{ T('field.examples') }}</b><code class="faint">examples</code></div><pre>{{ exText(viewing.def) }}</pre></div>
            <div class="sent"><div class="sh"><b>{{ T('field.tools') }}</b><code class="faint">tools</code></div><pre>{{ viewing.def.tools.join('\n') || '—' }}</pre></div>
            <div class="sent"><div class="sh"><b>{{ T('field.output') }}</b><code class="faint">output</code></div><pre>{{ viewing.def.output.format || '—' }}{{ viewing.def.output.schema ? `\n${viewing.def.output.schema}` : '' }}</pre></div>
          </template>
        </div>
        <div class="modal-f"><button class="btn" type="button" @click="viewing = null">{{ $t('c.close') }}</button></div>
      </div>
    </div>
  </div>
</template>
