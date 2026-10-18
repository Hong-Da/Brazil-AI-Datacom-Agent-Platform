<script setup lang="ts">
/**
 * 从设备生成草稿：选同一平台族的一台或几台设备 → POST /templates/draft（候选变量、类型、可选块 / 重复块候选、自检）→
 * 在模板文件里确认变量与约束 → PUT /templates/{id} 保存。哪些值真正是变量由人确认。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import TermName from '@/components/term-name.vue'
import { ApiError, errorText, get, post, put } from '@/api'
import type { Device } from '@/views/devices/logic'
import { msg, show } from '@/views/m3/texts'
import type { DraftResult, TemplateIssue } from './types'

const props = defineProps<{ devices: Device[]; profiles: { id: string; family: string }[] }>()
const emit = defineEmits<{ (e: 'saved', id: string): void }>()
const { t, locale } = useI18n()
const lang = computed(() => String(locale.value))

const step = ref(1)
const picked = ref<number[]>([])
const tplId = ref(`draft-${new Date().toISOString().slice(0, 10)}`)
const tplTitle = ref('')
const famOf = (d: Device) => props.profiles.find((p) => p.id === d.profile)?.family ?? d.vendor
const firstFam = computed(() => {
  const d = props.devices.find((x) => x.id === picked.value[0])
  return d ? famOf(d) : ''
})
const off = (d: Device) => !!firstFam.value && famOf(d) !== firstFam.value
function toggle(id: number, on: boolean): void {
  picked.value = on ? [...picked.value, id] : picked.value.filter((x) => x !== id)
}

const running = ref(false)
const err = ref('')
const res = ref<DraftResult | null>(null)
const yaml = ref('')
async function run(): Promise<void> {
  running.value = true
  err.value = ''
  try {
    const configs = []
    for (const id of picked.value) {
      const d = props.devices.find((x) => x.id === id)!
      const vs = (await get<{ versions: { id: number; latest: boolean }[] }>(`/devices/${id}/versions`)).versions
      const vid = vs.find((v) => v.latest)?.id ?? vs[0]?.id
      const src = await get<{ text: string }>(`/devices/${id}/versions/${vid}/text`)
      configs.push({ label: d.name, text: src.text })
    }
    res.value = await post<DraftResult>('/templates/draft', { configs, template_id: tplId.value.trim() || 'draft', title: tplTitle.value.trim() || null })
    yaml.value = res.value.source
    step.value = 2
  } catch (e) {
    err.value = errorText(e)
  } finally {
    running.value = false
  }
}

const saving = ref(false)
const saveErr = ref('')
const issues = ref<TemplateIssue[]>([])
const savedId = ref('')
async function save(): Promise<void> {
  saving.value = true
  saveErr.value = ''
  issues.value = []
  const m = /^id:\s*(\S+)/m.exec(yaml.value)
  const id = m ? m[1].replace(/^["']|["']$/g, '') : tplId.value
  try {
    await put(`/templates/${encodeURIComponent(id)}`, { source: yaml.value })
    savedId.value = id
    emit('saved', id)
  } catch (e) {
    saveErr.value = errorText(e)
    if (e instanceof ApiError && e.data && typeof e.data === 'object') issues.value = ((e.data as { issues?: TemplateIssue[] }).issues ?? [])
  } finally {
    saving.value = false
  }
}
const issueText = (i: TemplateIssue) => `${i.where ? i.where + '：' : ''}${msg(i.key, i.args ?? {}, lang.value)}`
const STEPS = ['templates.dStep1', 'templates.dStep2', 'templates.dStep3']
</script>

<template>
  <div data-testid="tpl-draft">
    <div class="steps">
      <div v-for="(s, i) in STEPS" :key="s" class="st" :class="i + 1 < step ? 'done' : i + 1 === step ? 'cur' : ''" @click="i + 1 < step || res ? (step = i + 1) : null">
        <span class="no">{{ i + 1 < step ? '✓' : i + 1 }}</span><span>{{ t(s) }}</span>
      </div>
    </div>

    <template v-if="step === 1">
      <p class="muted" style="margin-bottom: 10px">{{ $t('templates.dPickHint') }}</p>
      <div class="devs">
        <label v-for="d in devices" :key="d.id" class="devc" :class="{ off: off(d) && !picked.includes(d.id) }">
          <input type="checkbox" :checked="picked.includes(d.id)" :disabled="off(d) && !picked.includes(d.id)" :data-testid="`tpl-dpick-${d.id}`" @change="toggle(d.id, ($event.target as HTMLInputElement).checked)">
          <span><span class="nm">{{ d.name }}</span><br><span class="sub">{{ d.profile }}<template v-if="off(d) && !picked.includes(d.id)"> · {{ $t('templates.dOtherFam') }}</template></span></span>
        </label>
        <div v-if="!devices.length" class="faint small">{{ $t('templates.dNoDevices') }}</div>
      </div>
      <div class="row wrap mt12" style="align-items: flex-end">
        <span class="field" style="max-width: 300px; flex: 1"><label>{{ $t('templates.dId') }}</label><input v-model="tplId" class="input mono" data-testid="tpl-did"></span>
        <span class="field" style="max-width: 360px; flex: 1"><label>{{ $t('templates.dTitle') }}</label><input v-model="tplTitle" class="input"></span>
        <span class="ml-auto" />
        <button class="btn btn-primary" type="button" :disabled="!picked.length || running" data-testid="tpl-drun" @click="run"><Icon name="wand" small />{{ running ? $t('templates.dRunning') : $t('templates.dRun') }}</button>
      </div>
      <div v-if="err" class="notice err mt12"><Icon name="err" /><div class="grow">{{ err }}</div></div>
    </template>

    <template v-else-if="step === 2 && res">
      <div class="dstat">
        <div><div class="n">{{ res.vars.length }}</div><div class="k">{{ $t('templates.dVars') }}</div><div class="s">{{ $t('templates.dVarsS') }}</div></div>
        <div><div class="n">{{ res.optional_candidates.length }}</div><div class="k">{{ $t('templates.dOpt') }}</div><div class="s">{{ $t('templates.dOptS') }}</div></div>
        <div><div class="n">{{ res.repeat_candidates.length }}</div><div class="k">{{ $t('templates.dRep') }}</div><div class="s">{{ $t('templates.dRepS') }}</div></div>
        <div><div class="n">{{ res.verify.filter((v) => v.compliant).length }} / {{ res.verify.length }}</div><div class="k">{{ $t('templates.dVerify') }}</div><div class="s">{{ $t('templates.dVerifyS') }}</div></div>
      </div>
      <div class="notice info mt12"><Icon name="info" /><div>{{ $t('templates.dNote') }}</div></div>
      <div class="backtest mt12">
        <span v-for="v in res.verify" :key="v.device" class="bt"><span class="rk" :class="v.compliant ? 'match' : 'violation'">{{ v.compliant ? $t('templates.compliant') : $t('templates.errorsN', { n: v.errors }) }}</span><span class="nm">{{ v.device }}</span></span>
      </div>
      <div class="tbl-wrap mt12">
        <table class="tbl dt" data-testid="tpl-dvars">
          <thead><tr><th>{{ $t('templates.vName') }}</th><th>{{ $t('templates.vType') }}</th><th v-for="c in res.configs" :key="c" class="mono">{{ c }}</th><th>{{ $t('templates.dWhere') }}</th></tr></thead>
          <tbody>
            <tr v-for="v in res.vars" :key="v.name">
              <td><span class="vname">{{ v.name }}</span></td>
              <td><span class="vtype">{{ v.type }}</span></td>
              <td v-for="(x, k) in res.configs" :key="k" class="dv" :class="{ none: v.values[k] === null || v.values[k] === undefined }">{{ v.values[k] === null || v.values[k] === undefined ? $t('templates.none') : show(v.values[k]) }}</td>
              <td class="why"><template v-for="(p, k) in v.positions.slice(0, 3)" :key="k"><span class="srcchip">L{{ p.line }}</span> <TermName v-if="p.node" :id="p.node" /><span v-else class="mono">{{ p.schema }}</span><br></template></td>
            </tr>
            <tr v-if="!res.vars.length"><td :colspan="3 + res.configs.length" class="faint small">{{ $t('templates.dNoVars') }}</td></tr>
          </tbody>
        </table>
      </div>
      <template v-if="res.optional_candidates.length || res.repeat_candidates.length">
        <div class="sec-k mt16">{{ $t('templates.dBlocks') }}</div>
        <ul class="cands">
          <li v-for="o in res.optional_candidates" :key="o.node"><span class="blk-tag" style="margin: 0 6px 0 0">{{ $t('templates.optional') }}</span><TermName :id="o.node" /> <span class="faint small">{{ $t('templates.dMissingIn', { list: o.missing_in.join(', ') }) }}</span></li>
          <li v-for="(r, k) in res.repeat_candidates" :key="'r' + k"><span class="blk-tag rep" style="margin: 0 6px 0 0">{{ $t('templates.repeat') }}</span><span class="mono">{{ r.schema }}</span> × {{ r.count }} <span class="faint small">{{ r.parent }}</span></li>
        </ul>
      </template>
      <div v-for="(n, k) in res.notes" :key="k" class="notice mt8"><Icon name="info" /><div>{{ msg(n.key, n, lang) }}<template v-if="n.line"> · L{{ n.line }} <span class="mono">{{ n.text }}</span></template></div></div>
      <div class="row mt16" style="justify-content: space-between">
        <button class="btn" type="button" @click="step = 1"><Icon name="chevL" small />{{ $t('c.back') }}</button>
        <button class="btn btn-primary" type="button" data-testid="tpl-dnext" @click="step = 3">{{ $t('c.next') }}<Icon name="chevR" small /></button>
      </div>
    </template>

    <template v-else-if="step === 3 && res">
      <div class="m3box">
        <div class="m3box-h"><h3>{{ $t('templates.dYaml') }}</h3><span class="tag draft">draft</span></div>
        <textarea v-model="yaml" class="yaml-ed mono" spellcheck="false" data-testid="tpl-dyaml" />
        <div class="m3box-f"><Icon name="info" small /><span>{{ $t('templates.dYamlNote') }}</span></div>
      </div>
      <div v-if="saveErr" class="notice err mt12" data-testid="tpl-dsave-error"><Icon name="err" /><div class="grow">{{ saveErr }}<ul v-if="issues.length" class="issues"><li v-for="(i, k) in issues" :key="k">{{ issueText(i) }}</li></ul></div></div>
      <div v-if="savedId" class="notice ok mt12"><Icon name="ok" /><div>{{ $t('templates.savedAs', { id: savedId }) }}</div></div>
      <div class="row mt16" style="justify-content: space-between">
        <button class="btn" type="button" @click="step = 2"><Icon name="chevL" small />{{ $t('c.back') }}</button>
        <button class="btn btn-primary" type="button" :disabled="saving" data-testid="tpl-dsave" @click="save"><Icon name="check" small />{{ saving ? $t('templates.saving') : $t('templates.dSave') }}</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.steps { margin-bottom: 14px; }
.steps .st { cursor: pointer; }
.devs { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 8px; }
.devc { display: flex; gap: 10px; align-items: flex-start; border: 1px solid var(--line); border-radius: 6px; padding: 10px; cursor: pointer; background: var(--surface); }
.devc:has(input:checked) { border-color: var(--teal); background: var(--teal-soft); }
.devc.off { opacity: .55; cursor: not-allowed; }
.devc input { accent-color: var(--teal); margin-top: 3px; }
.devc .nm { font-weight: 600; font-family: var(--font-mono); font-size: 12.5px; }
.devc .sub { font-size: 11.5px; color: var(--ink-3); }
.dstat { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
.dstat > div { padding: 10px 14px; border-left: 1px solid var(--line); }
.dstat > div:first-child { border-left: 0; }
.dstat .n { font: 600 20px/1.2 var(--font-display); }
.dstat .k { font-size: 12px; color: var(--ink-2); }
.dstat .s { font-size: 11.5px; color: var(--ink-3); margin-top: 2px; }
.dt td { vertical-align: top; }
.dt .dv { font: 11.5px var(--font-mono); color: var(--ink-2); max-width: 180px; overflow-wrap: anywhere; }
.dt .dv.none { color: var(--ink-3); font-family: var(--font-ui); font-style: italic; }
.dt .why { font-size: 12px; color: var(--ink-2); max-width: 320px; }
.srcchip { font-size: 10.5px; border: 1px dotted var(--line-strong); border-radius: 3px; padding: 0 4px; color: var(--ink-3); white-space: nowrap; }
.backtest { display: flex; gap: 10px; flex-wrap: wrap; }
.bt { border: 1px solid var(--line); border-radius: 6px; padding: 8px 12px; display: flex; gap: 8px; align-items: center; font-size: 12.5px; }
.bt .nm { font-family: var(--font-mono); font-weight: 600; }
.cands { margin: 0; padding-left: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; }
.yaml-ed { width: 100%; min-height: 460px; border: 0; padding: 10px 12px; font-size: 12px; line-height: 1.55; background: var(--surface); color: var(--ink); resize: vertical; outline: none; }
.issues { margin: 6px 0 0; padding-left: 18px; }
@media (max-width: 900px) { .dstat { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
