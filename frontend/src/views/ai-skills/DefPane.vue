<script setup lang="ts">
/** 定义：系统提示词、提示模板、附加模板、示例（few-shot）、变量、允许的工具、输出格式、代码校验（只读）；保存为新版本并生效。 */
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { ApiError, put } from '@/api'
import PromptEditor from './PromptEditor.vue'
import { useSkillCtx, useT } from './ctx'
import { br, cloneDef, issueKey, moveItem, saveBody, unknownVars, varWhere, vname } from './logic'
import type { Issue } from './types'

const { detail, draft, dirty, reload, flash } = useSkillCtx()
const { T, L } = useT()
const hot = ref('')
const note = ref('')
const saving = ref(false)
const issues = ref<Issue[]>([])
const warnings = ref<Issue[]>([])
const newEx = ref<Set<number>>(new Set())

const d = computed(() => draft.value!)
const known = computed(() => (detail.value?.variables ?? []).map((v) => v.name))
const unk = computed(() => (detail.value && draft.value ? unknownVars(draft.value, detail.value.variables) : []))
const nextVer = computed(() => (detail.value?.versions ?? 0) + 1)
const baseName = computed(() => vname(detail.value?.active) ?? T('ver.builtinLower'))
const canSave = computed(() => dirty.value && !unk.value.length && !saving.value)

function issueText(x: Issue): string {
  const k = issueKey(x.key)
  const p = Object.fromEntries(Object.entries(x.params ?? {}).map(([a, b]) => [a, String(b)]))
  return `${fieldLabel(x.field)}：${T(k, p)}`
}
function fieldLabel(f: string): string {
  if (f.startsWith('templates.')) return T('field.template', { n: f.slice(10) })
  const m = /^examples\.(\d+)$/.exec(f)
  if (m) return T('field.exampleN', { n: Number(m[1]) + 1 })
  return ['system', 'prompt', 'examples', 'tools', 'output', 'templates'].includes(f) ? T(`field.${f}`) : f
}
function toggleTool(id: string, on: boolean): void {
  const s = new Set(d.value.tools)
  if (on) s.add(id)
  else s.delete(id)
  d.value.tools = [...s]
}
function addExample(): void {
  d.value.examples.push({ input: '', output: '', note: '' })
  newEx.value.add(d.value.examples.length - 1)
}
function move(i: number, dir: -1 | 1): void {
  d.value.examples = moveItem(d.value.examples, i, dir)
  newEx.value = new Set()
}
function delEx(i: number): void {
  d.value.examples.splice(i, 1)
  newEx.value = new Set()
}
function discard(): void {
  if (detail.value) draft.value = cloneDef(detail.value.definition)
  issues.value = []
  warnings.value = []
  newEx.value = new Set()
  flash(T('def.discarded'))
}
async function save(): Promise<void> {
  if (!detail.value || !draft.value) return
  saving.value = true
  issues.value = []
  try {
    const r = await put<{ version: string; unchanged: boolean; warnings: Issue[] }>(`/ai/skills/${detail.value.id}`, saveBody(draft.value, note.value.trim()))
    warnings.value = r.warnings ?? []
    note.value = ''
    newEx.value = new Set()
    await reload(false)
    flash(r.unchanged ? T('def.unchanged') : T('def.saved', { v: r.version }))
  } catch (e) {
    if (e instanceof ApiError && e.status === 422) {
      const data = e.data as { issues?: Issue[]; warnings?: Issue[] } | null
      issues.value = data?.issues ?? []
      warnings.value = data?.warnings ?? []
    }
    flash(e instanceof Error ? e.message : String(e))
  } finally { saving.value = false }
}
function fit(e: Event): void {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight + 2}px`
}
</script>

<template>
  <div v-if="detail && draft" data-testid="sk-def">
    <div class="def-grid">
      <div class="col">
        <section class="panel">
          <div class="panel-h"><h2>{{ T('field.system') }}</h2><span class="meta">{{ T('def.systemMeta') }}</span></div>
          <div class="panel-b"><PromptEditor v-model="d.system" :known="known" :hot="hot" label="system" testid="pe-system" /></div>
        </section>
        <section class="panel">
          <div class="panel-h"><h2>{{ T('field.prompt') }}</h2><span class="meta">{{ T('def.promptMeta') }}</span></div>
          <div class="panel-b"><PromptEditor v-model="d.prompt" :known="known" :hot="hot" label="prompt" testid="pe-prompt" /></div>
        </section>
        <section class="panel">
          <div class="panel-h"><h2>{{ T('def.templates') }}</h2><span class="meta">{{ T('def.templatesMeta') }}</span></div>
          <div class="panel-b">
            <template v-if="Object.keys(d.templates).length">
              <div v-for="(_, name, i) in d.templates" :key="name" :style="i ? { marginTop: '12px' } : undefined">
                <div class="tpl-h"><code>{{ name }}</code></div>
                <PromptEditor v-model="d.templates[name]" :known="known" :hot="hot" :label="String(name)" :testid="`pe-tpl-${name}`" />
              </div>
            </template>
            <p v-else class="small faint">{{ T('def.noTemplates') }}</p>
          </div>
        </section>
        <section class="panel">
          <div class="panel-h">
            <h2>{{ T('def.examples') }} <span class="faint small">{{ d.examples.length }}</span></h2><span class="meta">{{ T('def.examplesMeta') }}</span>
            <button class="btn btn-sm ml-auto" type="button" data-testid="ex-add" @click="addExample"><Icon name="plus" small />{{ T('def.addExample') }}</button>
          </div>
          <div class="panel-b">
            <div v-if="!d.examples.length" class="notice info"><Icon name="info" /><div>{{ T('def.noExamples') }}</div></div>
            <div v-for="(e, i) in d.examples" :key="i" class="ex" :class="{ 'is-new': newEx.has(i), 'is-bad': !e.input.trim() || !e.output.trim() }" data-testid="ex-item">
              <div class="no">{{ i + 1 }}</div>
              <div class="io">
                <span class="k">{{ T('def.exInput') }}</span><textarea v-model="e.input" class="textarea" rows="1" @input="fit" />
                <span class="k">{{ T('def.exOutput') }}</span><textarea v-model="e.output" class="textarea" rows="1" @input="fit" />
                <span class="k">{{ T('def.exNote') }}</span><input v-model="e.note" class="input note" :placeholder="T('def.exNotePh')">
              </div>
              <div class="ops">
                <button class="btn btn-ghost btn-sm btn-icon" type="button" :disabled="i === 0" :title="T('def.up')" :aria-label="T('def.up')" @click="move(i, -1)"><Icon name="up" small /></button>
                <button class="btn btn-ghost btn-sm btn-icon" type="button" :disabled="i === d.examples.length - 1" :title="T('def.down')" :aria-label="T('def.down')" @click="move(i, 1)"><Icon name="chevD" small /></button>
                <button class="btn btn-ghost btn-sm btn-icon" type="button" :title="$t('c.delete')" :aria-label="$t('c.delete')" @click="delEx(i)"><Icon name="trash" small /></button>
              </div>
            </div>
          </div>
        </section>
      </div>
      <div class="col">
        <section class="panel">
          <div class="panel-h"><h2>{{ T('def.vars') }}</h2><span class="meta">{{ T('def.varsMeta') }}</span></div>
          <div class="panel-b">
            <div class="varlist">
              <div v-for="v in detail.variables" :key="v.name" class="vr" :class="{ unused: !varWhere(d, v.name).length }">
                <button type="button" class="pv" :class="{ 'is-hot': hot === v.name }" :title="T('def.hotTip')" @click="hot = hot === v.name ? '' : v.name">{{ br(v.name) }}</button>
                <span>{{ L(v.desc) }}</span>
                <span class="where">{{ varWhere(d, v.name).join(' · ') || T('def.unused') }}</span>
              </div>
            </div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-h"><h2>{{ T('def.tools') }}</h2></div>
          <div class="panel-b">
            <label v-for="tc in detail.tool_choices" :key="tc.id" class="tool">
              <input type="checkbox" :checked="d.tools.includes(tc.id)" :data-testid="`tool-${tc.id}`" @change="toggleTool(tc.id, ($event.target as HTMLInputElement).checked)">
              <span><b>{{ L(tc.title) }}</b><code>{{ tc.id }}</code></span>
            </label>
          </div>
        </section>
        <section class="panel">
          <div class="panel-h"><h2>{{ T('def.output') }}</h2></div>
          <div class="panel-b" style="display: flex; flex-direction: column; gap: 8px">
            <div class="seg" role="group" data-testid="out-format">
              <button v-for="f in detail.output_formats" :key="f" type="button" :aria-pressed="d.output.format === f" @click="d.output.format = f">{{ T(`fmt.${f}`) }}</button>
            </div>
            <input v-model="d.output.schema" class="input mono" :aria-label="T('def.output')">
            <span class="small faint">{{ T('def.outputNote') }}</span>
          </div>
        </section>
        <section class="panel">
          <div class="panel-h"><h2>{{ T('def.checks') }}</h2></div>
          <div class="panel-b">
            <div class="checks">
              <div v-for="c in detail.checks" :key="c" class="ck"><Icon name="shield" small /><code>{{ c }}</code><span>{{ L(detail.check_titles[c]) || c }}</span></div>
            </div>
            <div class="ro-note"><Icon name="lock" small />{{ T('def.checksRo') }}</div>
          </div>
        </section>
      </div>
    </div>
    <div v-if="issues.length" class="notice err mt12" data-testid="def-issues">
      <Icon name="err" />
      <div class="grow"><b>{{ T('def.issuesTitle', { n: issues.length }) }}</b><ul class="issues"><li v-for="(x, i) in issues" :key="i">{{ issueText(x) }}</li></ul></div>
    </div>
    <div v-if="warnings.length" class="notice warn mt12" data-testid="def-warnings">
      <Icon name="warn" />
      <div class="grow"><ul class="issues"><li v-for="(x, i) in warnings" :key="i">{{ issueText(x) }}</li></ul></div>
    </div>
    <section class="panel savebar" data-testid="savebar">
      <div>
        <textarea v-model="note" class="textarea" rows="1" :placeholder="T('def.notePh')" data-testid="save-note" />
        <div class="info">
          <span v-if="dirty" class="dirty"><Icon name="pencil" small />{{ T('def.dirty') }}</span><span v-else>{{ T('def.clean') }}</span>
          <span>{{ T('def.saveInfo', { v: nextVer, base: baseName }) }}</span>
          <span v-if="unk.length" class="bad">{{ T('def.cannotSave') }}</span>
        </div>
      </div>
      <div class="acts">
        <button class="btn" type="button" :disabled="!dirty" data-testid="def-discard" @click="discard">{{ T('def.discard') }}</button>
        <button class="btn btn-primary" type="button" :disabled="!canSave" data-testid="def-save" @click="save"><Icon name="check" small />{{ saving ? $t('c.running') : T('def.save') }}</button>
      </div>
    </section>
  </div>
</template>
