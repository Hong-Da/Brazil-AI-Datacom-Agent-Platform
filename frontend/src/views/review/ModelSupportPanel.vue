<script setup lang="ts">
/**
 * 审核队列里的型号支持申请（REQ-044，预览 DevelopDocs/ui-preview/REQ-044/review.html）：申请内容（设备、版本、当时的
 * Profile、未识别行写法）与维护员的三步——从现有 Profile 派生（继承，只写差异）、补差异与命令卡并发布、型号规则改指向并
 * 重新解析（所有项目，手工选择的不动）。接口：GET /kb/model-support/{id}、POST …/derive、POST …/retarget。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText, get, post } from '@/api'
import { condText, pct, type Candidate, type ModelRule } from '@/views/devices/model'

const props = defineProps<{ itemId: number }>()
const emit = defineEmits<{ (e: 'decided', approved: boolean): void }>()
const { t } = useI18n()

interface Payload {
  model: string
  reason: string
  device: string
  device_id: number
  project: string | null
  vendor: string
  version: string
  profile: string
  profile_source: string
  profile_rule_id: number | null
  unknown: number
  command: number
  unknown_ratio: number | null
  patterns: { pattern: string; count: number }[]
  suggested_rule: { name_pattern: string; version: string; feature: string }
}
interface PlanRule extends ModelRule { to: string; change: boolean }
interface Status {
  item: { id: number; status: string; payload: Payload; source: { user?: string } | null; created_at: string | null }
  derived: { profile: string; base: string; by: string; at: string } | null
  released: boolean
  plan: { rules: PlanRule[]; create_rule: { name_pattern: string; version: string; feature: string; profile: string } | null; devices: { id: number; name: string; project: string | null; profile: string; source: string }[] } | null
  bases: Candidate[]
  result: unknown
}
const st = ref<Status | null>(null)
const loadError = ref('')
const busy = ref(false)
const actError = ref('')
const doneMsg = ref('')
const form = reactive({ id: '', base: '', title: '', platform: '', software: '', version: '' })

const payload = computed(() => st.value?.item.payload ?? null)
const stage = computed(() => (!st.value?.derived ? 0 : st.value.released ? 2 : 1))

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9.]+/g, '-').replace(/^-+|-+$/g, '')
}
async function load(): Promise<void> {
  loadError.value = ''
  try {
    const d = await get<Status>(`/kb/model-support/${props.itemId}`)
    st.value = d
    const p = d.item.payload
    if (!form.base) {
      form.base = d.bases[0]?.profile ?? p.profile
      const ver = p.suggested_rule?.version ?? ''
      form.id = slug(`${p.vendor || 'x'}-${p.model}-${ver || p.version}`)
      form.title = `${p.model}${p.version ? ' ' + p.version : ''}`
      form.platform = p.model
      form.software = p.version
      form.version = ver
    }
  } catch (e) {
    loadError.value = errorText(e)
  }
}
onMounted(load)

async function derive(): Promise<void> {
  busy.value = true
  actError.value = ''
  try {
    await post(`/kb/model-support/${props.itemId}/derive`, { ...form })
    await load()
  } catch (e) {
    actError.value = errorText(e)
  } finally {
    busy.value = false
  }
}
async function retarget(): Promise<void> {
  busy.value = true
  actError.value = ''
  try {
    const r = await post<{ profile: string; rules_changed: number[]; rule_created: unknown; devices: unknown[] }>(`/kb/model-support/${props.itemId}/retarget`, {})
    doneMsg.value = t('model.ms.retargetDone', { p: r.profile, r: r.rules_changed.length + (r.rule_created ? 1 : 0), n: r.devices.length })
    emit('decided', true)
  } catch (e) {
    actError.value = errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="msp" :data-testid="`model-support-${itemId}`">
    <div v-if="loadError" class="notice err"><Icon name="err" /><div class="grow">{{ loadError }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
    <p v-else-if="!st || !payload" class="faint">{{ $t('c.loading') }}</p>
    <template v-else>
      <div class="info">
        <dl class="kv">
          <dt>{{ $t('model.fModel') }}</dt><dd>{{ payload.model }}</dd>
          <dt>{{ $t('model.ms.device') }}</dt><dd>{{ payload.device }}<template v-if="payload.project"> ({{ payload.project }})</template></dd>
          <dt>{{ $t('model.ms.vendorVer') }}</dt><dd>{{ payload.vendor || '—' }} · {{ payload.version || '—' }}</dd>
          <dt>{{ $t('model.ms.profileThen') }}</dt><dd>{{ payload.profile || '—' }} · {{ $t(`model.src.${payload.profile_source || 'auto'}`) }}<template v-if="payload.profile_rule_id"> #{{ payload.profile_rule_id }}</template></dd>
          <dt>{{ $t('model.ms.unknown') }}</dt><dd>{{ payload.unknown }} / {{ payload.command + payload.unknown }} ({{ pct(payload.unknown_ratio) }})</dd>
          <dt>{{ $t('model.ms.reason') }}</dt><dd class="ui">{{ payload.reason || '—' }}</dd>
        </dl>
        <div>
          <div class="small faint" style="margin-bottom: 6px">{{ $t('model.ms.patterns') }}</div>
          <div class="pats" data-testid="ms-patterns"><div v-for="p in payload.patterns" :key="p.pattern">{{ p.pattern }}<span v-if="p.count > 1" class="faint">   ×{{ p.count }}</span></div><div v-if="!payload.patterns.length" class="faint">—</div></div>
          <router-link class="btn btn-sm mt8" :to="{ name: 'unknown-lines' }"><Icon name="unknown" small />{{ $t('model.ms.openUnknown') }}</router-link>
        </div>
      </div>

      <div v-if="doneMsg" class="notice ok mt12" data-testid="ms-done"><Icon name="ok" /><div class="grow">{{ doneMsg }}</div></div>
      <div v-else class="flow mt12">
        <div class="stepc" :class="stage === 0 ? 'cur' : 'done'">
          <h3><span class="no"><Icon v-if="stage > 0" name="check" small /><template v-else>1</template></span>{{ $t('model.ms.step1') }}</h3>
          <template v-if="stage === 0">
            <label class="f">{{ $t('model.ms.base') }}
              <select v-model="form.base" class="select mono" data-testid="ms-base">
                <option v-for="b in st.bases" :key="b.profile" :value="b.profile">{{ b.profile }} · {{ pct(b.ratio) }}</option>
              </select>
            </label>
            <label class="f">{{ $t('model.ms.newId') }}<input v-model="form.id" class="input mono" data-testid="ms-id"></label>
            <label class="f">{{ $t('model.ms.fTitle') }}<input v-model="form.title" class="input"></label>
            <label class="f">{{ $t('model.ms.platform') }}<input v-model="form.platform" class="input"></label>
            <label class="f">{{ $t('model.ms.software') }}<input v-model="form.software" class="input mono"></label>
            <label class="f">{{ $t('model.ms.versionRule') }}<input v-model="form.version" class="input mono"></label>
            <p class="small faint">{{ $t('model.ms.deriveNote') }}</p>
            <button class="btn btn-primary" type="button" :disabled="busy || !form.id || !form.base" data-testid="ms-derive" @click="derive"><Icon name="branch" small />{{ $t('model.ms.derive') }}</button>
          </template>
          <div v-else class="diffbox">{{ $t('model.ms.derived', { p: st.derived?.profile, b: st.derived?.base }) }}</div>
        </div>
        <div class="stepc" :class="stage === 1 ? 'cur' : stage === 2 ? 'done' : ''">
          <h3><span class="no"><Icon v-if="stage > 1" name="check" small /><template v-else>2</template></span>{{ $t('model.ms.step2') }}</h3>
          <p class="small">{{ $t('model.ms.step2Note') }}</p>
          <div class="row" style="gap: 6px; flex-wrap: wrap">
            <router-link v-if="st.derived" class="btn btn-sm" :to="{ name: 'profiles', query: { profile: st.derived.profile } }"><Icon name="layers" small />{{ $t('model.ms.openProfile') }}</router-link>
            <router-link class="btn btn-sm" :to="{ name: 'releases' }"><Icon name="tag" small />{{ $t('model.ms.openReleases') }}</router-link>
          </div>
          <div v-if="st.derived && !st.released" class="notice warn" data-testid="ms-not-released"><Icon name="warn" /><div class="grow small">{{ $t('model.ms.notReleased', { p: st.derived.profile }) }}</div></div>
          <div v-else-if="st.derived" class="notice ok"><Icon name="ok" /><div class="grow small">{{ $t('model.ms.released', { p: st.derived.profile }) }}</div></div>
        </div>
        <div class="stepc" :class="stage >= 1 ? 'cur' : ''">
          <h3><span class="no">3</span>{{ $t('model.ms.step3') }}</h3>
          <template v-if="st.plan">
            <div class="small faint">{{ $t('model.ms.rulesToChange') }}</div>
            <table v-if="st.plan.rules.length" class="tbl compact">
              <tbody>
                <tr v-for="r in st.plan.rules" :key="r.id">
                  <td class="mono">#{{ r.id }} {{ $t(`model.scope.${r.scope}`) }}</td>
                  <td class="small">{{ condText(r) }}</td>
                  <td class="mono small"><template v-if="r.change">{{ r.profile }} → <b>{{ r.to }}</b></template><span v-else class="faint">{{ $t('model.ms.unchanged') }}</span></td>
                </tr>
              </tbody>
            </table>
            <p v-else-if="st.plan.create_rule" class="small">{{ $t('model.ms.noRule', { c: condText(st.plan.create_rule), p: st.plan.create_rule.profile }) }}</p>
            <div class="small faint mt8">{{ $t('model.ms.devicesToReparse', { n: st.plan.devices.length }) }}</div>
            <div class="small mono">{{ st.plan.devices.map((d) => (d.project ? d.project + ': ' : '') + d.name).join(', ') }}</div>
          </template>
          <button class="btn btn-primary" type="button" :disabled="busy || stage < 1" data-testid="ms-retarget" @click="retarget"><Icon name="refresh" small />{{ $t('model.ms.retarget') }}</button>
        </div>
      </div>
      <div v-if="actError" class="notice err mt12" data-testid="ms-error"><Icon name="err" /><div class="grow">{{ actError }}</div></div>
    </template>
  </div>
</template>

<style scoped>
.msp { padding: 4px 2px; }
.info { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 18px; }
.kv { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 6px 14px; margin: 0; font-size: 13px; }
.kv dt { color: var(--ink-3); }
.kv dd { margin: 0; font-family: var(--font-mono); font-size: 12.5px; }
.kv dd.ui { font-family: var(--font-ui); }
.pats, .diffbox { font: 12px var(--font-mono); border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; background: var(--surface-2); white-space: pre-wrap; max-height: 180px; overflow: auto; }
.flow { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.stepc { border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; background: var(--surface); display: flex; flex-direction: column; gap: 8px; }
.stepc.cur { border-color: var(--teal-line); box-shadow: 0 0 0 2px var(--teal-soft); }
.stepc h3 { font-size: 13.5px; display: flex; gap: 8px; align-items: center; margin: 0; }
.stepc h3 .no { width: 20px; height: 20px; border-radius: 50%; background: var(--surface-3); display: inline-flex; align-items: center; justify-content: center; font-size: 11px; }
.stepc.done h3 .no { background: var(--teal); color: var(--surface); }
.stepc label.f { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--ink-2); }
@media (max-width: 1100px) { .flow, .info { grid-template-columns: 1fr; } }
</style>
