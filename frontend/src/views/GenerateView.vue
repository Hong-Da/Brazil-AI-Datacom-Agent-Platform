<script setup lang="ts">
/**
 * 批量生成（预览 DevelopDocs/ui-preview/M3/generate.html）：模板 + 参数表（表格编辑 / CSV 上传）→ POST /templates/generate →
 * 每行的验证阶段与生成预览；通过的行打包为 ZIP 下载（前端只存储不压缩地打包，不需要额外依赖）。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import M3Code from '@/components/m3-code.vue'
import { errorText as apiErrorText, get, post } from '@/api'
import { pickLang } from '@/i18n'
import { saveText, toCsv } from '@/views/profiles/csv'
import { splitLines, type CodeLine } from '@/views/m3/code'
import { saveBytes, zipBytes } from '@/views/m3/zip'
import { paramColumns } from '@/views/templates/logic'
import type { TemplateDetail, TemplateInfo } from '@/views/templates/types'
import { alignCsv, cellErrors, exampleRow, parseCsv, reportMd, resultCsvRows, stages, toCsvText, type GenResult } from './generate/logic'

interface ProfileLite { id: string; family: string }

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const lang = computed(() => String(locale.value))

const templates = ref<TemplateInfo[]>([])
const profiles = ref<ProfileLite[]>([])
const loadError = ref('')
const tplId = ref<string>(String(route.query.template ?? ''))
const detail = ref<TemplateDetail | null>(null)
const engine = ref<'text' | 'canon'>('text')
const targetProfile = ref('')

const cols = computed(() => (detail.value ? paramColumns(detail.value.vars, detail.value.blocks) : []))
const varOfCol = (c: string) => detail.value?.vars.find((v) => v.name === c)
const blockOfCol = (c: string) => detail.value?.blocks.find((b) => b.name === c || c.startsWith(`${b.name}.`))
const rows = ref<string[][]>([])
const sel = ref(0)
const filter = ref<'' | 'bad'>('')
const note = ref('')

async function loadBase(): Promise<void> {
  loadError.value = ''
  try {
    const [l, p] = await Promise.all([get<{ templates: TemplateInfo[] }>('/templates'), get<{ profiles: ProfileLite[] }>('/kb/profiles')])
    templates.value = l.templates.filter((x) => x.valid)
    profiles.value = p.profiles
    if (!tplId.value || !templates.value.some((x) => x.id === tplId.value)) tplId.value = templates.value[0]?.id ?? ''
  } catch (e) {
    loadError.value = apiErrorText(e)
  }
}

/** 从模板校验页带来的一行参数（sessionStorage，只用一次） */
function takeImport(id: string): Record<string, string> | null {
  try {
    const raw = sessionStorage.getItem('lmesh-gen-import')
    if (!raw) return null
    const v = JSON.parse(raw) as { template: string; row: Record<string, string> }
    if (v.template !== id) return null
    sessionStorage.removeItem('lmesh-gen-import')
    return v.row
  } catch {
    return null
  }
}

async function loadTemplate(id: string): Promise<void> {
  detail.value = null
  result.value = null
  runError.value = ''
  if (!id) return
  try {
    detail.value = await get<TemplateDetail>(`/templates/${encodeURIComponent(id)}`)
  } catch (e) {
    loadError.value = apiErrorText(e)
    return
  }
  targetProfile.value = detail.value.profile
  const imp = route.query.from === 'check' ? takeImport(id) : null
  rows.value = imp ? [cols.value.map((c) => imp[c] ?? '')] : [exampleRow(cols.value, detail.value.vars, detail.value.blocks)]
  note.value = imp ? t('generate.imported') : t('generate.exampleNote')
  sel.value = 0
  void router.replace({ query: { template: id } })
  schedule(0)
}
watch(tplId, (id) => { void loadTemplate(id) })
watch([engine, targetProfile], () => schedule(0))

// ---------------- 生成与验证 ----------------
const running = ref(false)
const runError = ref('')
const result = ref<GenResult | null>(null)
const stale = ref(false)
const ranAt = ref('')
let timer = 0
let seq = 0
function schedule(ms = 700): void {
  stale.value = true
  window.clearTimeout(timer)
  timer = window.setTimeout(() => { void run() }, ms)
}
onBeforeUnmount(() => window.clearTimeout(timer))

async function run(): Promise<void> {
  if (!detail.value || !rows.value.length) {
    result.value = null
    stale.value = false
    return
  }
  const my = ++seq
  running.value = true
  runError.value = ''
  const body: Record<string, unknown> = { template_id: detail.value.id, csv: toCsvText(cols.value, rows.value), engine: engine.value, verify: true, include_text: true }
  if (engine.value === 'canon' && targetProfile.value) body.target_profile = targetProfile.value
  try {
    const r = await post<GenResult>('/templates/generate', body)
    if (my !== seq) return
    result.value = r
    ranAt.value = new Date().toLocaleString()
    stale.value = false
  } catch (e) {
    if (my !== seq) return
    runError.value = apiErrorText(e)
    result.value = null
  } finally {
    if (my === seq) running.value = false
  }
}

/** 后端跳过全空的行：按非空行对齐结果 */
const rowResult = computed(() => {
  const m = new Map<number, GenResult['rows'][number]>()
  if (!result.value) return m
  let k = 0
  rows.value.forEach((r, i) => {
    if (r.some((x) => (x ?? '').trim())) {
      const g = result.value!.rows[k++]
      if (g) m.set(i, g)
    }
  })
  return m
})
const okN = computed(() => [...rowResult.value.values()].filter((r) => r.ok).length)
const badN = computed(() => [...rowResult.value.values()].filter((r) => !r.ok).length)

function edit(i: number, k: number, v: string): void {
  rows.value[i][k] = v
  sel.value = i
  schedule()
}
function addRow(): void {
  rows.value.push(cols.value.map(() => ''))
  sel.value = rows.value.length - 1
}
function delRow(i: number): void {
  rows.value.splice(i, 1)
  sel.value = Math.max(0, Math.min(sel.value, rows.value.length - 1))
  schedule(0)
}

// ---------------- CSV ----------------
const fileIn = ref<HTMLInputElement>()
async function onCsv(ev: Event): Promise<void> {
  const input = ev.target as HTMLInputElement
  const f = input.files?.[0]
  input.value = ''
  if (!f) return
  const a = alignCsv(parseCsv(await f.text()), cols.value)
  if (!a.rows.length) {
    note.value = t('generate.csvEmpty')
    return
  }
  rows.value = a.rows
  sel.value = 0
  note.value = [t('generate.csvLoaded', { n: a.rows.length }), a.ignored.length ? t('generate.csvIgnored', { list: a.ignored.join(', ') }) : '', a.missing.length ? t('generate.csvMissing', { list: a.missing.join(', ') }) : ''].filter(Boolean).join(' ')
  schedule(0)
}
function headerCsv(): void {
  if (!detail.value) return
  saveText(`${detail.value.id}-params.csv`, toCsv([cols.value, exampleRow(cols.value, detail.value.vars, detail.value.blocks)]))
}

// ---------------- 选中行：验证阶段与预览 ----------------
const selRes = computed(() => rowResult.value.get(sel.value))
const selStages = computed(() => (selRes.value ? stages(selRes.value, lang.value) : []))
const cellErr = (i: number) => cellErrors(rowResult.value.get(i), cols.value, lang.value)
const preview = computed<CodeLine[]>(() => {
  const r = selRes.value
  const unk = new Set((r?.checks.parse?.unknown_lines ?? []).map((u) => u.line))
  return splitLines(r?.text).map((s, i) => ({ no: i + 1, text: s, cls: [unk.has(i + 1) ? 'unknown' : '', /^\s*[!#]/.test(s) ? 'c-cmt' : ''].join(' ') }))
})
const STAGE_ICON = { ok: 'check', bad: 'x', skip: 'minus' } as const

// ---------------- 下载 ----------------
const dlOpen = ref(false)
const okRows = computed(() => [...rowResult.value.values()].filter((r) => r.ok && r.text))
function doZip(): void {
  const r = result.value
  if (!r || !detail.value) return
  const files = okRows.value.map((x) => ({ name: x.file, text: x.text! }))
  files.push({ name: 'report-zh-CN.md', text: reportMd(r, 'zh-CN', ranAt.value) }, { name: 'report-en.md', text: reportMd(r, 'en', ranAt.value) })
  files.push({ name: 'params-with-results.csv', text: toCsv(resultCsvRows(cols.value, rows.value, r, lang.value)) })
  saveBytes(`generate-${detail.value.id}-${new Date().toISOString().slice(0, 10)}.zip`, zipBytes(files))
  dlOpen.value = false
}
function dlOne(): void {
  const r = selRes.value
  if (r?.text) saveText(r.file, r.text, 'text/plain;charset=utf-8')
}

onMounted(async () => {
  const before = tplId.value
  await loadBase()
  if (before && tplId.value === before) void loadTemplate(before)
})
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.tpl') }}</span><span class="sep">/</span><span>{{ $t('nav.generate') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('generate.title') }}</h1>
          <p class="ph-sub">{{ $t('generate.sub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn btn-primary" type="button" :disabled="!okRows.length || stale" data-testid="gen-download" @click="dlOpen = true"><Icon name="download" small />{{ $t('generate.download') }}</button>
        </div>
      </div>
      <div v-if="loadError" class="notice err" style="margin-bottom: 12px"><Icon name="err" /><div class="grow">{{ loadError }}</div><button class="btn btn-sm" type="button" @click="loadBase">{{ $t('c.retry') }}</button></div>

      <section class="panel setup" aria-label="Setup" data-testid="gen-setup">
        <div class="panel-b">
          <div class="field"><label>{{ $t('generate.template') }}</label>
            <select v-model="tplId" class="select" data-testid="gen-template">
              <option v-if="!templates.length" value="">{{ $t('generate.noTemplates') }}</option>
              <option v-for="x in templates" :key="x.id" :value="x.id">{{ x.id }} v{{ x.version }} · {{ pickLang(x.title, lang) }}</option>
            </select>
          </div>
          <div class="field"><label>{{ $t('generate.engine') }}</label>
            <div class="seg" role="group">
              <button type="button" :aria-pressed="engine === 'text'" :title="$t('generate.engineTextTip')" data-testid="gen-engine-text" @click="engine = 'text'">{{ $t('generate.engineText') }}</button>
              <button type="button" :aria-pressed="engine === 'canon'" :title="$t('generate.engineCanonTip')" data-testid="gen-engine-canon" @click="engine = 'canon'">{{ $t('generate.engineCanon') }}</button>
            </div>
          </div>
          <div v-if="engine === 'canon'" class="field"><label>{{ $t('generate.target') }}</label>
            <select v-model="targetProfile" class="select" data-testid="gen-target">
              <option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.id }}</option>
            </select>
          </div>
          <span style="flex: 1" />
          <div class="row wrap">
            <button class="btn" type="button" :disabled="!detail" data-testid="gen-header" @click="headerCsv"><Icon name="download" small />{{ $t('generate.header') }}</button>
            <button class="btn" type="button" :disabled="!detail" data-testid="gen-upload" @click="fileIn?.click()"><Icon name="upload" small />{{ $t('generate.upload') }}</button>
            <input ref="fileIn" type="file" accept=".csv,text/csv" hidden data-testid="gen-csv-input" @change="onCsv">
          </div>
        </div>
      </section>

      <div v-if="note" class="notice info mt12"><Icon name="info" /><div class="grow">{{ note }}</div></div>
      <div v-if="runError" class="notice err mt12" data-testid="gen-error"><Icon name="err" /><div class="grow">{{ runError }}</div><button class="btn btn-sm" type="button" @click="run">{{ $t('c.retry') }}</button></div>

      <template v-if="detail">
        <div class="gsum" data-testid="gen-sum">
          <h2>{{ $t('generate.table') }}</h2>
          <span class="cnt">{{ $t('generate.rows') }} <b>{{ rows.length }}</b></span>
          <span class="cnt"><span class="rst ok"><Icon name="ok" />{{ $t('generate.passed') }}</span><b data-testid="gen-ok">{{ okN }}</b></span>
          <span class="cnt"><span class="rst bad"><Icon name="err" />{{ $t('generate.failed') }}</span><b data-testid="gen-bad">{{ badN }}</b></span>
          <span v-if="running || stale" class="small faint" data-testid="gen-running">{{ $t('generate.checking') }}</span>
          <span class="seg" role="group" style="margin-left: auto">
            <button type="button" :aria-pressed="filter === ''" @click="filter = ''">{{ $t('generate.all') }}</button>
            <button type="button" :aria-pressed="filter === 'bad'" @click="filter = 'bad'">{{ $t('generate.onlyBad') }}</button>
          </span>
        </div>
        <section class="panel" aria-label="Parameter table">
          <div class="pgrid-wrap">
            <table class="pgrid" data-testid="gen-grid">
              <thead>
                <tr>
                  <th class="rh">{{ $t('generate.rowResult') }}</th>
                  <th v-for="c in cols" :key="c" :title="pickLang(varOfCol(c)?.title, lang)">
                    <span class="vname">{{ c }}</span>
                    <span v-if="varOfCol(c)" class="vtype">{{ varOfCol(c)?.type }}</span>
                    <span v-if="blockOfCol(c)" class="blk-tag" :class="{ rep: blockOfCol(c)?.kind === 'repeat' }" style="margin-left: 4px">{{ blockOfCol(c)?.kind === 'repeat' ? $t('generate.rep') : $t('generate.opt') }}</span>
                  </th>
                  <th />
                </tr>
              </thead>
              <tbody>
                <template v-for="(r, i) in rows" :key="i">
                  <tr v-if="filter !== 'bad' || rowResult.get(i)?.ok === false" :class="{ 'is-sel': sel === i }" data-testid="gen-row">
                    <td class="rh" @click="sel = i">
                      <span class="rn">{{ i + 1 }}</span>
                      <span v-if="!rowResult.get(i)" class="rst faint">—</span>
                      <span v-else-if="rowResult.get(i)!.ok" class="rst ok" data-testid="gen-row-ok"><Icon name="ok" />{{ $t('generate.rowOk') }}</span>
                      <span v-else class="rst bad" data-testid="gen-row-bad"><Icon name="err" />{{ $t('generate.rowErr', { n: rowResult.get(i)!.errors.length }) }}</span>
                    </td>
                    <td v-for="(c, k) in cols" :key="c">
                      <input
                        :value="r[k]" :class="{ bad: cellErr(i).has(c) }" :title="cellErr(i).get(c)?.join('; ')" :aria-invalid="cellErr(i).has(c) || undefined"
                        :aria-label="`${c} ${i + 1}`" :data-testid="`gen-cell-${i}-${c}`" @input="edit(i, k, ($event.target as HTMLInputElement).value)" @focus="sel = i"
                      >
                    </td>
                    <td><button class="btn btn-ghost btn-icon btn-sm rowdel" type="button" :title="$t('generate.delRow')" :aria-label="$t('generate.delRow')" @click="delRow(i)"><Icon name="trash" small /></button></td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
          <div class="gfoot">
            <button class="btn btn-sm" type="button" data-testid="gen-add" @click="addRow"><Icon name="plus" small />{{ $t('generate.addRow') }}</button>
            <span>{{ $t('generate.foot') }}</span>
          </div>
        </section>

        <div class="gw">
          <section class="panel" aria-label="Row checks" data-testid="gen-ladder">
            <div class="panel-h"><h2>{{ $t('generate.checksOf', { n: sel + 1 }) }} <span class="mono faint">{{ selRes?.device }}</span></h2></div>
            <div v-if="!selRes" class="empty small">{{ running || stale ? $t('generate.checking') : $t('generate.noResult') }}</div>
            <div v-else class="ladder">
              <div v-for="s in selStages" :key="s.key" class="lad" :class="s.state" :data-testid="`gen-stage-${s.key}`">
                <span class="dot"><Icon :name="STAGE_ICON[s.state]" /></span>
                <div>
                  <div class="lt">{{ $t(`generate.st.${s.key}`) }}</div>
                  <div class="ls">{{ s.state === 'skip' ? (s.note === 'cross' ? $t('generate.stCross') : $t('generate.stSkip')) : $t(`generate.sd.${s.key}`) }}</div>
                  <ul v-if="s.items.length && s.state === 'bad'"><li v-for="(x, k) in s.items" :key="k">{{ x }}</li></ul>
                </div>
              </div>
            </div>
          </section>
          <section class="panel prev" aria-label="Preview">
            <div class="box-h">
              <h3>{{ $t('generate.preview') }}</h3>
              <span class="mono faint">{{ selRes?.file }}</span>
              <span v-if="selRes && !selRes.ok" class="tag fail">{{ $t('generate.notDl') }}</span>
              <span class="ml-auto" />
              <button v-if="selRes?.text" class="btn btn-xs" type="button" @click="dlOne"><Icon name="download" small />{{ $t('generate.dlOne') }}</button>
            </div>
            <M3Code v-if="preview.length" :lines="preview" testid="gen-preview" class="prevcode" />
            <div v-else class="empty small">{{ selRes ? $t('generate.noText') : '—' }}</div>
          </section>
        </div>
      </template>
      <div v-else-if="!loadError && templates.length" class="empty mt16">{{ $t('c.loading') }}</div>
    </div>

    <div v-if="dlOpen && result" class="modal-back" @click.self="dlOpen = false" @keydown.esc="dlOpen = false">
      <div class="modal" role="dialog" aria-modal="true" style="width: min(640px, 100%)" data-testid="gen-dl-dialog">
        <div class="modal-h"><h2>{{ $t('generate.download') }}</h2><button class="btn btn-ghost btn-icon btn-sm" type="button" :aria-label="$t('c.close')" @click="dlOpen = false"><Icon name="x" small /></button></div>
        <div class="modal-b">
          <p class="muted" style="margin-bottom: 10px">{{ $t('generate.zipNote') }}</p>
          <div class="dl-files">
            <template v-for="(r, i) in rows" :key="i">
              <div v-if="rowResult.get(i)">
                <template v-if="rowResult.get(i)!.ok"><Icon name="file" small />{{ rowResult.get(i)!.file }}</template>
                <template v-else><span class="x">{{ rowResult.get(i)!.file }}</span><span class="rst bad" style="font-family: var(--font-ui)">{{ $t('generate.excluded') }}</span></template>
              </div>
            </template>
            <div><Icon name="report" small />report-zh-CN.md</div>
            <div><Icon name="report" small />report-en.md</div>
            <div><Icon name="rows" small />params-with-results.csv</div>
          </div>
          <div v-if="badN" class="notice warn mt12"><Icon name="warn" /><div>{{ $t('generate.zipBad', { n: badN }) }}</div></div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="dlOpen = false">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="button" data-testid="gen-zip" @click="doZip"><Icon name="zip" small />{{ $t('generate.zip') }}</button>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.setup .panel-b { display: flex; gap: 12px 18px; flex-wrap: wrap; align-items: flex-end; }
.setup .field { min-width: 0; }
.setup .select { width: auto; min-width: 260px; max-width: 100%; }
.gsum { display: flex; gap: 8px 18px; align-items: center; flex-wrap: wrap; margin: 16px 0 10px; }
.gsum h2 { font-size: 15px; }
.gsum .cnt { display: inline-flex; gap: 6px; align-items: center; font-size: 12.5px; color: var(--ink-2); }
.gsum .cnt b { font: 600 15px var(--font-display); color: var(--ink); }
.gsum .seg button { height: 26px; }
.pgrid-wrap { overflow: auto; max-height: 360px; }
.pgrid { border-collapse: separate; border-spacing: 0; width: max-content; min-width: 100%; }
.pgrid th { position: sticky; top: 0; z-index: 2; background: var(--surface-2); border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left; font-size: 12px; white-space: nowrap; }
.pgrid th .vname { font-size: 11.5px; }
.pgrid th .vtype { margin-left: 4px; font-size: 10.5px; }
.pgrid th.rh, .pgrid td.rh { position: sticky; left: 0; z-index: 1; background: var(--surface); }
.pgrid th.rh { z-index: 3; background: var(--surface-2); }
.pgrid td { border-bottom: 1px solid var(--line); padding: 3px 4px; vertical-align: middle; }
.pgrid tr.is-sel td { background: var(--blue-soft); }
.pgrid tr.is-sel td.rh { box-shadow: inset 3px 0 0 var(--sel-ring); background: var(--blue-soft); }
.pgrid td.rh { padding: 3px 8px; white-space: nowrap; cursor: pointer; }
.pgrid .rn { font: 600 11.5px var(--font-ui); color: var(--ink-3); display: inline-block; width: 18px; }
.pgrid input { font: 12px var(--font-mono); height: 26px; border: 1px solid transparent; background: transparent; color: var(--ink); padding: 0 6px; border-radius: 4px; width: 100%; min-width: 120px; }
.pgrid input:hover { border-color: var(--line); }
.pgrid input:focus { outline: none; border-color: var(--blue); background: var(--surface); box-shadow: 0 0 0 3px color-mix(in srgb, var(--blue) 18%, transparent); }
.pgrid input.bad { border-color: var(--red); background: color-mix(in srgb, var(--red-soft) 70%, transparent); color: var(--red-ink); }
.rst { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px; font-weight: 600; }
.rst.ok { color: var(--teal-ink); }
.rst.bad { color: var(--red-ink); }
.rst :deep(.ico) { width: 14px; height: 14px; }
.pgrid .rowdel { opacity: 0; }
.pgrid tr:hover .rowdel, .pgrid .rowdel:focus { opacity: 1; }
.gfoot { display: flex; gap: 8px; align-items: center; padding: 8px 12px; border-top: 1px solid var(--line); font-size: 12px; color: var(--ink-2); flex-wrap: wrap; }
.gw { display: grid; grid-template-columns: 380px minmax(0, 1fr); gap: 12px; margin-top: 12px; align-items: start; }
@media (max-width: 1100px) { .gw { grid-template-columns: minmax(0, 1fr); } }
.ladder { padding: 6px 0; }
.lad { display: grid; grid-template-columns: 26px minmax(0, 1fr); gap: 10px; padding: 8px 14px; position: relative; }
.lad::before { content: ""; position: absolute; left: 26px; top: 30px; bottom: -8px; border-left: 1.5px solid var(--line); }
.lad:last-child::before { display: none; }
.lad .dot { width: 24px; height: 24px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; border: 1.5px solid var(--line-strong); background: var(--surface); position: relative; z-index: 1; }
.lad .dot :deep(.ico) { width: 14px; height: 14px; }
.lad.ok .dot { background: var(--teal); border-color: var(--teal); color: #fff; }
:root[data-theme="dark"] .lad.ok .dot { color: #06201D; }
.lad.bad .dot { background: var(--red-soft); border-color: var(--red); color: var(--red-ink); }
.lad.skip .dot { border-style: dashed; color: var(--ink-3); }
.lad .lt { font-weight: 600; font-size: 12.5px; display: flex; gap: 8px; align-items: center; }
.lad .ls { font-size: 12px; color: var(--ink-2); margin-top: 2px; }
.lad.skip .lt { color: var(--ink-3); }
.lad ul { margin: 6px 0 0; padding-left: 16px; font-size: 12px; color: var(--red-ink); }
.lad ul li { margin: 2px 0; overflow-wrap: anywhere; }
.prev .box-h { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-bottom: 1px solid var(--line); flex-wrap: wrap; font-size: 12px; }
.prev .box-h h3 { font-size: 12.5px; }
.prevcode { max-height: 560px; }
.dl-files { border: 1px solid var(--line); border-radius: 6px; max-height: 260px; overflow: auto; }
.dl-files div { display: flex; gap: 8px; align-items: center; padding: 6px 10px; border-top: 1px solid var(--line); font: 12px var(--font-mono); }
.dl-files div:first-child { border-top: 0; }
.dl-files .x { color: var(--ink-3); text-decoration: line-through; }
</style>
