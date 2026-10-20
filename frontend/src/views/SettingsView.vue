<script setup lang="ts">
// 系统设置（REQ-049，管理员）：与首次运行向导同一份参数定义与校验（GET/PUT /settings），写入 config/config.toml；
// 需要重启的项标出并在保存后列出，不自动重启服务。
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, ApiError } from '@/api'
import Icon from '@/components/Icon.vue'
import { LANGS } from '@/i18n'
import { labelKey, optionKey } from './wizard/wizard'
import { changedKeys, controlOf, pendingText, type SField, type SGroup, type SettingsData } from './settings/settings'

const { t, te } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`settings.${k}`, p ?? {})

const data = ref<SettingsData | null>(null)
const loadErr = ref('')
const edits = reactive<Record<string, string | number>>({})
const errors = reactive<Record<string, string>>({})
const saving = ref(false)
const saveErr = ref('')
const justSaved = ref<string[]>([])
const active = ref('')

async function load(): Promise<void> {
  loadErr.value = ''
  try {
    data.value = await api<SettingsData>('/settings')
    active.value = active.value || data.value.groups[0]?.id || ''
  } catch (e) { loadErr.value = (e as Error).message }
}
onMounted(load)

const changed = computed(() => (data.value ? changedKeys(data.value.groups, edits) : []))
const restartChanged = computed(() => changed.value.filter((k) => fieldOf(k)?.restart))

function fieldOf(key: string): SField | undefined {
  return data.value?.groups.flatMap((g) => g.fields).find((f) => f.key === key)
}
function label(f: SField): string { return te(labelKey(f.key)) ? t(labelKey(f.key)) : f.key }
function optLabel(f: SField, c: string): string {
  if (f.key === 'ui.language') return LANGS.find((l) => l.code === c)?.label ?? c
  const k = optionKey(f.key, f.kind, c)
  return k && te(k) ? t(k) : c || t('wizard.none')
}
function cur(f: SField): string { return String(f.key in edits ? edits[f.key] : f.value ?? '') }
function groupChanged(g: SGroup): number { return g.fields.filter((f) => changed.value.includes(f.key)).length }

function setValue(f: SField, raw: string): void {
  delete errors[f.key]
  const v: string | number = (f.kind === 'int' || f.kind === 'port') && /^\s*-?\d+\s*$/.test(raw) ? Number(raw) : raw
  if (String(v) === String(f.value ?? '')) delete edits[f.key]
  else edits[f.key] = v
}
/** 输入后校验这一项（端口占用等由服务端判断）。 */
async function check(f: SField): Promise<void> {
  if (!(f.key in edits)) return
  try {
    await api('/settings', { method: 'PUT', body: JSON.stringify({ values: { [f.key]: edits[f.key] }, dry_run: true }) })
  } catch (e) {
    const errs = e instanceof ApiError && e.data && typeof e.data === 'object' && 'errors' in e.data ? (e.data as { errors: Record<string, string> }).errors : null
    if (errs?.[f.key]) errors[f.key] = errs[f.key]
  }
}
function discard(): void {
  for (const k of Object.keys(edits)) delete edits[k]
  for (const k of Object.keys(errors)) delete errors[k]
  saveErr.value = ''
}
async function save(): Promise<void> {
  if (!changed.value.length) return
  saving.value = true
  saveErr.value = ''
  try {
    const r = await api<SettingsData & { changed: string[] }>('/settings', { method: 'PUT', body: JSON.stringify({ values: { ...edits } }) })
    data.value = r
    justSaved.value = r.changed
    discard()
    window.scrollTo({ top: 0 })
  } catch (e) {
    const errs = e instanceof ApiError && e.data && typeof e.data === 'object' && 'errors' in e.data ? (e.data as { errors: Record<string, string> }).errors : null
    if (errs) Object.assign(errors, errs)
    else saveErr.value = (e as Error).message
  } finally { saving.value = false }
}
const errorCount = computed(() => Object.keys(errors).length)
function go(id: string): void {
  active.value = id
  document.getElementById(`set-g-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.settings') }}</h1>
          <p class="ph-sub">{{ T('sub') }}</p>
        </div>
        <div v-if="data" class="ph-actions small faint">{{ T('writesTo') }} <code data-testid="set-path">{{ data.config_path }}</code></div>
      </div>

      <div v-if="loadErr" class="notice err"><Icon name="err" /><div class="grow">{{ loadErr }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
      <div v-else-if="!data" class="empty">{{ $t('c.loading') }}</div>
      <template v-else>
        <div v-if="data.restart_pending.length" class="notice warn restart" data-testid="set-restart">
          <Icon name="warn" />
          <div class="grow">
            <b>{{ justSaved.length ? T('savedRestart', { n: data.restart_pending.length }) : T('pendingRestart', { n: data.restart_pending.length }) }}</b>
            <ul>
              <li v-for="p in data.restart_pending" :key="p.key" :data-testid="`set-restart-${p.key}`">
                {{ fieldOf(p.key) ? label(fieldOf(p.key)!) : p.key }}
                <span class="mono">{{ pendingText(p.running, t('settings.secretSet'), t('settings.secretUnset')) }}</span> →
                <span class="mono">{{ pendingText(p.saved, t('settings.secretSet'), t('settings.secretUnset')) }}</span>
              </li>
            </ul>
            <div class="small">{{ T('restartHow') }}</div>
          </div>
          <span class="tag t-amber">{{ T('restartPendingTag') }}</span>
        </div>
        <div v-else-if="justSaved.length" class="notice ok" data-testid="set-saved"><Icon name="ok" /><div class="grow">{{ T('savedNow', { n: justSaved.length }) }}</div></div>

        <div class="set-layout">
          <nav class="set-rail" aria-label="Groups">
            <a v-for="g in data.groups" :key="g.id" href="#" :aria-current="active === g.id" :data-testid="`set-nav-${g.id}`" @click.prevent="go(g.id)">
              <span>{{ g.title }}</span>
              <span :class="['n', { chg: groupChanged(g) }]">{{ groupChanged(g) ? T('nChanged', { n: groupChanged(g) }) : g.fields.length }}</span>
            </a>
          </nav>
          <div>
            <section v-for="g in data.groups" :id="`set-g-${g.id}`" :key="g.id" class="panel set-g" :data-testid="`set-group-${g.id}`">
              <div class="panel-h"><h2>{{ g.title }}</h2></div>
              <div v-for="f in g.fields" :key="f.key"
                :class="['set-r', { 'is-chg': changed.includes(f.key) && !errors[f.key], 'is-err': errors[f.key], 'is-ro': f.readonly }]"
                :data-testid="`set-row-${f.key}`">
                <div>
                  <div class="lbl">
                    <label :for="`set-${f.key}`">{{ label(f) }}</label> <code>{{ f.key }}</code>
                    <span v-if="f.restart" class="tag t-amber" data-testid="set-restart-tag">{{ T('restartTag') }}</span>
                    <span v-if="f.readonly === 'env'" class="tag t-violet">{{ T('envTag') }}</span>
                  </div>
                  <div class="desc">{{ f.desc }}</div>
                  <div v-if="f.readonly" class="desc ro-note">{{ T(`ro_${f.readonly}`) }}</div>
                </div>
                <div class="ctl">
                  <router-link v-if="f.readonly === 'ai'" class="btn btn-sm" :to="{ name: 'ai-settings' }"><Icon name="spark" small />{{ T('openAi') }}</router-link>
                  <input v-else-if="controlOf(f) === 'secret'" :id="`set-${f.key}`" class="input" :value="f.value ? T('secretSet') : T('secretUnset')" disabled />
                  <select v-else-if="controlOf(f) === 'select'" :id="`set-${f.key}`" class="select" :value="cur(f)" :disabled="!!f.readonly"
                    :data-testid="`set-${f.key}`" @change="setValue(f, ($event.target as HTMLSelectElement).value); check(f)">
                    <option v-for="c in f.choices" :key="c" :value="c">{{ optLabel(f, c) }}</option>
                  </select>
                  <input v-else :id="`set-${f.key}`" :class="['input', 'mono', { 'is-error': errors[f.key] }]" :value="cur(f)" :disabled="!!f.readonly"
                    :inputmode="f.kind === 'int' || f.kind === 'port' ? 'numeric' : undefined" spellcheck="false" autocomplete="off" :aria-invalid="!!errors[f.key]"
                    :data-testid="`set-${f.key}`" @input="setValue(f, ($event.target as HTMLInputElement).value)" @change="check(f)" />
                  <span v-if="errors[f.key]" class="err" role="alert"><Icon name="err" small />{{ errors[f.key] }}</span>
                  <span v-else-if="changed.includes(f.key)" class="hint">{{ T('was', { v: f.kind === 'choice' || f.kind === 'bool' ? optLabel(f, String(f.value)) : f.value }) }}</span>
                </div>
              </div>
            </section>
          </div>
        </div>

        <div v-if="changed.length || errorCount || saveErr" class="set-bar" data-testid="set-bar">
          <span class="st">
            <template v-if="errorCount"><span class="bad"><Icon name="err" small />{{ T('fixFirst', { n: errorCount }) }}</span></template>
            <template v-else>
              <b>{{ changed.length }}</b>{{ T('changedN') }}
              <span v-if="restartChanged.length" class="pending-r">{{ T('restartN', { n: restartChanged.length }) }}</span>
            </template>
            <span v-if="saveErr" class="bad">{{ saveErr }}</span>
          </span>
          <button type="button" class="btn" data-testid="set-discard" @click="discard">{{ T('discard') }}</button>
          <button type="button" class="btn btn-primary" :disabled="saving || !!errorCount || !changed.length" data-testid="set-save" @click="save">
            <Icon name="check" small />{{ saving ? $t('c.loading') : T('save') }}
          </button>
        </div>
      </template>
    </div>
  </main>
</template>

<style scoped>
.set-layout { display: grid; grid-template-columns: 200px minmax(0, 1fr); gap: 16px; align-items: start; }
.set-rail { position: sticky; top: 12px; display: flex; flex-direction: column; gap: 2px; }
.set-rail a { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 6px; color: var(--ink-2); text-decoration: none; font-size: 13px; }
.set-rail a:hover { background: var(--surface-3); color: var(--ink); }
.set-rail a[aria-current="true"] { background: var(--surface); color: var(--ink); font-weight: 600; box-shadow: inset 0 0 0 1px var(--line); }
.set-rail .n { margin-left: auto; font-size: 11px; color: var(--ink-3); font-weight: 400; }
.set-rail .n.chg { color: var(--teal-ink); font-weight: 600; }
.set-g { scroll-margin-top: 12px; }
.set-g + .set-g { margin-top: 14px; }
.set-r { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 300px); gap: 6px 22px; padding: 13px 16px; border-top: 1px solid var(--line); align-items: start; position: relative; }
.panel-h + .set-r { border-top: 0; }
.set-r .lbl { font-weight: 600; font-size: 13px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.set-r .lbl code { font: 11.5px var(--font-mono); color: var(--ink-3); font-weight: 400; }
.set-r .desc { color: var(--ink-2); font-size: 12.5px; margin-top: 3px; max-width: 70ch; }
.set-r .ro-note { color: var(--ink-3); }
.set-r .ctl { display: flex; flex-direction: column; gap: 5px; }
.set-r .ctl .btn { align-self: flex-start; }
.set-r .ctl .hint { font-size: 11.5px; color: var(--ink-3); }
.set-r .ctl .err { font-size: 12px; color: var(--red-ink); display: flex; gap: 5px; align-items: center; }
.set-r.is-chg { background: color-mix(in srgb, var(--teal-soft) 38%, transparent); }
.set-r.is-chg::before, .set-r.is-err::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--teal); }
.set-r.is-err { background: color-mix(in srgb, var(--red-soft) 50%, transparent); }
.set-r.is-err::before { background: var(--red); }
.set-r.is-ro .ctl .input, .set-r.is-ro .ctl .select { background: var(--surface-2); color: var(--ink-2); }
.tag.t-violet { background: var(--violet-soft); color: var(--violet); border-color: transparent; }
.restart { margin-bottom: 14px; }
.restart ul { margin: 4px 0 6px; padding-left: 18px; font-size: 12.5px; }
.notice.ok { margin-bottom: 14px; }
.set-bar { position: sticky; bottom: 0; z-index: 4; margin-top: 16px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow-pop);
  padding: 10px 14px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.set-bar .st { margin-right: auto; font-size: 12.5px; color: var(--ink-2); display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.set-bar .bad { color: var(--red-ink); display: inline-flex; gap: 6px; align-items: center; }
.pending-r { font-size: 12px; color: var(--amber-ink); }
@media (max-width: 1100px) {
  .set-layout { grid-template-columns: 1fr; }
  .set-rail { position: static; flex-direction: row; flex-wrap: wrap; }
}
@media (max-width: 720px) { .set-r { grid-template-columns: 1fr; } }
</style>
