<script setup lang="ts">
/**
 * 设备页“更换 Profile 并重新解析”（REQ-044，预览 DevelopDocs/ui-preview/REQ-044/devices.html）：
 * GET /devices/{id}/profile-candidates 给出当前选择、按选择顺序会自动选到的 Profile、试解析的候选（按识别比例排序）；
 * 可改回自动、可同时记住为型号规则（全局只限维护员与管理员）；PUT /devices/{id}/profile 保存并重新解析最新版本。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText, get, put } from '@/api'
import { useAuth } from '@/stores/auth'
import { hasCondition, pct, regexOk, type Candidate, type MatchLevel, type ModelRule, type ProfileSource, type RuleConds, type RuleScope } from './model'

const props = defineProps<{ deviceId: number; deviceName: string }>()
const emit = defineEmits<{ close: []; done: [msg: string] }>()
const { t } = useI18n()
const auth = useAuth()

interface Cands {
  device: { id: number; name: string; vendor: string; version: string; family: string | null }
  profile: string
  profile_source: ProfileSource
  match_level: MatchLevel
  unknown_ratio: number | null
  rule: ModelRule | null
  auto: { profile: string; source: ProfileSource }
  candidates: Candidate[]
  recommended: string | null
  suggested_rule: RuleConds
}
const data = ref<Cands | null>(null)
const loadError = ref('')
const pick = ref('') // 空 = 改回自动
const remember = ref(false)
const scope = ref<RuleScope>('project')
const rule = reactive<RuleConds>({ name_pattern: '', version: '', feature: '' })
const saving = ref(false)
const saveError = ref('')

async function load(): Promise<void> {
  loadError.value = ''
  try {
    const d = await get<Cands>(`/devices/${props.deviceId}/profile-candidates`)
    data.value = d
    pick.value = d.profile_source === 'manual' ? d.profile : d.recommended ?? d.profile
    Object.assign(rule, d.suggested_rule)
  } catch (e) {
    loadError.value = errorText(e)
  }
}
const ruleOk = computed(() => !remember.value || !pick.value || (hasCondition(rule) && regexOk(rule.version) && regexOk(rule.feature)))

async function save(): Promise<void> {
  saving.value = true
  saveError.value = ''
  try {
    const body = { profile: pick.value || null, remember: remember.value && pick.value ? { scope: scope.value, ...rule } : null }
    const r = await put<{ profile: string; profile_source: ProfileSource; unknown_ratio: number | null }>(`/devices/${props.deviceId}/profile`, body)
    emit('done', t('model.chgDone', { d: props.deviceName, p: r.profile || '—', s: t(`model.src.${r.profile_source}`), r: pct(r.unknown_ratio) }))
  } catch (e) {
    saveError.value = errorText(e)
  } finally {
    saving.value = false
  }
}
function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape' && !saving.value) emit('close')
}
onMounted(() => { void load(); document.addEventListener('keydown', onKey) })
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="modal-back" data-testid="profile-dialog" @click.self="!saving && emit('close')">
    <div class="modal" style="width: min(740px, 100%)" role="dialog" aria-modal="true" aria-labelledby="pdT">
      <div class="modal-h">
        <h2 id="pdT">{{ $t('model.chgTitle') }} · <span class="mono">{{ deviceName }}</span></h2>
        <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" :disabled="saving" @click="emit('close')"><Icon name="x" /></button>
      </div>
      <div class="modal-b">
        <div v-if="loadError" class="notice err"><Icon name="err" /><div class="grow">{{ loadError }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
        <p v-else-if="!data" class="faint">{{ $t('c.loading') }}</p>
        <template v-else>
          <dl class="kv">
            <dt>{{ $t('model.current') }}</dt>
            <dd>{{ data.profile || '—' }} <span class="src-chip" :class="data.profile_source">{{ $t(`model.src.${data.profile_source}`) }}<template v-if="data.rule"> #{{ data.rule.id }}</template></span> <span class="unk-r">{{ $t('model.unk', { p: pct(data.unknown_ratio) }) }}</span></dd>
            <dt>{{ $t('model.detected') }}</dt>
            <dd>{{ data.device.vendor || $t('devices.vendorUnknown') }} · {{ data.device.version || '—' }}</dd>
          </dl>
          <p class="small faint mt12">{{ data.device.vendor ? $t('model.candHint') : $t('model.candHintAll') }}</p>
          <div class="cands mt8" role="radiogroup" data-testid="profile-cands">
            <label v-for="c in data.candidates" :key="c.profile" class="cand" :class="{ on: pick === c.profile }">
              <input v-model="pick" type="radio" :value="c.profile" :data-testid="`profile-cand-${c.profile}`">
              <span>
                <span class="pid">{{ c.profile }}</span><span v-if="data.device.vendor && c.profile === data.recommended" class="rec-mark">{{ $t('model.recommended') }}</span>
                <div class="meta">{{ c.title }} · command {{ c.command }} · unknown {{ c.unknown }}<template v-if="c.exact"> · {{ $t('model.src.auto') }}</template><template v-else-if="c.fallback"> · {{ $t('model.src.fallback') }}</template></div>
              </span>
              <span class="bar"><i :style="{ width: `${(c.ratio * 100).toFixed(1)}%` }" /></span>
              <span class="pct">{{ pct(c.ratio) }}</span>
            </label>
            <label class="cand" :class="{ on: pick === '' }">
              <input v-model="pick" type="radio" value="" data-testid="profile-cand-auto">
              <span><span class="pid">{{ $t('model.backAuto') }}</span><div class="meta">{{ $t('model.backAutoD', { p: data.auto.profile || '—' }) }}</div></span>
              <span /><span />
            </label>
          </div>
          <div v-if="pick" class="remember">
            <label class="row" style="gap: 6px"><input v-model="remember" type="checkbox" data-testid="profile-remember"><b>{{ $t('model.rememberRule') }}</b></label>
            <div v-if="remember" class="grid">
              <label class="f">{{ $t('model.fScope') }}
                <select v-model="scope" class="select">
                  <option value="project">{{ $t('model.scope.project') }}</option>
                  <option value="global" :disabled="!auth.isKbEditor">{{ auth.isKbEditor ? $t('model.scope.global') : $t('model.globalOnly') }}</option>
                </select>
              </label>
              <label class="f">{{ $t('model.fName') }}<input v-model="rule.name_pattern" class="input mono"></label>
              <label class="f">{{ $t('model.fVersion') }}<input v-model="rule.version" class="input mono"></label>
              <label class="f" style="grid-column: 1 / -1">{{ $t('model.fFeature') }}<input v-model="rule.feature" class="input mono" placeholder="^set neid"></label>
            </div>
            <div v-if="remember && !ruleOk" class="small" style="color: var(--amber-ink); margin-top: 6px">{{ hasCondition(rule) ? $t('model.badRegex') : $t('model.needCond') }}</div>
          </div>
          <div class="notice info mt12"><Icon name="info" /><div class="grow small">{{ $t('model.chgNote') }}</div></div>
          <div v-if="saveError" class="notice err mt12" data-testid="profile-error"><Icon name="err" /><div class="grow">{{ saveError }}</div></div>
        </template>
      </div>
      <div class="modal-f">
        <button class="btn" type="button" :disabled="saving" @click="emit('close')">{{ $t('c.cancel') }}</button>
        <button class="btn btn-primary" type="button" :disabled="!data || saving || !ruleOk" data-testid="profile-save" @click="save"><Icon name="refresh" small />{{ $t('model.chgGo') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kv { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 6px 14px; margin: 0; font-size: 13px; }
.kv dt { color: var(--ink-3); }
.kv dd { margin: 0; font-family: var(--font-mono); font-size: 12.5px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.src-chip { display: inline-flex; align-items: center; font-family: var(--font-ui); font-size: 11px; padding: 0 6px; border-radius: 3px; border: 1px dashed var(--line-strong); color: var(--ink-2); white-space: nowrap; }
.src-chip.fallback, .src-chip.manual, .src-chip.rule { border-style: solid; border-color: var(--amber-line); color: var(--amber-ink); background: var(--amber-soft); }
.src-chip.none { border-style: solid; border-color: var(--red-line); color: var(--red-ink); background: var(--red-soft); }
.unk-r { font: 11px var(--font-mono); color: var(--ink-3); }
.cands { display: flex; flex-direction: column; gap: 2px; border: 1px solid var(--line); border-radius: 8px; padding: 4px; max-height: 320px; overflow: auto; }
.cand { display: grid; grid-template-columns: 18px minmax(0, 1fr) 120px 56px; gap: 8px; align-items: center; padding: 6px 8px; border-radius: 6px; cursor: pointer; }
.cand:hover { background: var(--surface-3); }
.cand.on { background: var(--teal-soft); }
.cand .pid { font: 12px var(--font-mono); }
.cand .meta { font-size: 11px; color: var(--ink-3); }
.cand .bar { height: 6px; border-radius: 3px; background: var(--surface-3); overflow: hidden; }
.cand .bar i { display: block; height: 100%; background: var(--teal); }
.cand .pct { font: 600 12px var(--font-mono); text-align: right; }
.rec-mark { font-size: 10.5px; font-weight: 700; color: var(--teal-ink); border: 1px solid var(--teal-line); background: var(--teal-soft); border-radius: 3px; padding: 0 4px; margin-left: 6px; }
.remember { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; background: var(--surface-2); margin-top: 10px; }
.remember .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px 12px; margin-top: 8px; }
.remember label.f { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--ink-2); }
@media (max-width: 760px) { .remember .grid { grid-template-columns: 1fr; } .cand { grid-template-columns: 18px minmax(0, 1fr) 56px; } .cand .bar { display: none; } }
</style>
