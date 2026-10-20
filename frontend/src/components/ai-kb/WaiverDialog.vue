<script setup lang="ts">
/**
 * 基线例外说明（baseline-waiver，M8-5；预览 compliance.html“其他入口”）：对某台设备的一条不符合项起草例外理由与补偿措施。
 * 只生成文字（text_only），不改规则与审计结果；下方汇总两段可复制的文字（已采纳的优先）。
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { get } from '@/api'
import Icon from '@/components/Icon.vue'
import AiEntryButton from '@/components/ai-suggest/AiEntryButton.vue'
import AiSuggestPanel from '@/components/ai-suggest/AiSuggestPanel.vue'
import { projectPath, query, type ListResult, type Suggestion } from '@/components/ai-suggest/logic'
import { useProject } from '@/stores/project'
import { waiverScope, waiverTexts } from './compliance'

const props = defineProps<{ deviceId: number; deviceName: string; rule: string; ruleTitle: string; baseline: string }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`kb-ai.${k}`, p ?? {})
const project = useProject()

const panel = ref<InstanceType<typeof AiSuggestPanel> | null>(null)
const aiState = ref('loading')
const items = ref<Suggestion[]>([])
const copied = ref('')
const scope = computed(() => waiverScope(props.deviceId, props.baseline, props.rule))
const params = computed(() => ({ device_id: props.deviceId, rule: props.rule, baseline: props.baseline }))
const texts = computed(() => waiverTexts(items.value))

async function refresh(): Promise<void> {
  if (!project.ref) return
  try {
    items.value = (await get<ListResult>(projectPath(project.ref, `/ai/suggestions${query({ skill: 'baseline-waiver', scope: scope.value, limit: 50 })}`))).items
  } catch {
    /* 面板里会显示加载错误 */
  }
}

async function run(): Promise<void> {
  await nextTick()
  await panel.value?.start()
}

function copy(which: 'reason' | 'compensating' | 'all'): void {
  const s = which === 'all'
    ? `${T('bw.reason')}\n${texts.value.reason}\n\n${T('bw.comp')}\n${texts.value.compensating}`
    : texts.value[which]
  const done = () => { copied.value = which; setTimeout(() => { if (copied.value === which) copied.value = '' }, 1500) }
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(s).then(done, done)
  else done()
}

onMounted(refresh)
</script>

<template>
  <div class="modal-back" data-testid="baseline-waiver" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="bwTitle" style="width: min(760px, 100%)">
      <div class="modal-h">
        <h2 id="bwTitle">{{ T('bw.title', { rule: ruleTitle || rule }) }}</h2>
        <span class="ml-auto" />
        <AiEntryButton :skills="['baseline-waiver']" :busy="aiState === 'running'" small @run="run" />
        <button class="btn btn-sm btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" data-testid="baseline-waiver-close" @click="emit('close')"><Icon name="x" small /></button>
      </div>
      <div class="modal-b bw-b">
        <p class="small muted">{{ T('bw.sub', { d: deviceName, b: baseline }) }} <code class="small">{{ rule }}</code></p>
        <AiSuggestPanel ref="panel" skill="baseline-waiver" :params="params" :scope="scope" flat @state="aiState = $event" @changed="refresh" />
        <section class="bw-out" data-testid="baseline-waiver-texts">
          <p v-if="!texts.reason && !texts.compensating" class="small faint">{{ T('bw.none') }}</p>
          <template v-else>
            <div v-for="k in (['reason', 'compensating'] as const)" :key="k" class="bw-t">
              <div class="bw-th"><b>{{ T(k === 'reason' ? 'bw.reason' : 'bw.comp') }}</b>
                <button class="btn btn-xs ml-auto" type="button" :disabled="!texts[k]" :data-testid="`baseline-waiver-copy-${k}`" @click="copy(k)"><Icon :name="copied === k ? 'check' : 'copy'" small />{{ copied === k ? T('bw.copied') : T('bw.copy') }}</button>
              </div>
              <p class="bw-txt" :data-testid="`baseline-waiver-${k}`">{{ texts[k] || '—' }}</p>
            </div>
          </template>
        </section>
      </div>
      <div class="modal-f">
        <button class="btn btn-sm" type="button" :disabled="!texts.reason && !texts.compensating" data-testid="baseline-waiver-copy-all" @click="copy('all')"><Icon :name="copied === 'all' ? 'check' : 'copy'" small />{{ copied === 'all' ? T('bw.copied') : T('bw.copyAll') }}</button>
        <button class="btn btn-sm btn-primary" type="button" @click="emit('close')">{{ $t('c.close') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-h { gap: 8px; }
.bw-b { display: flex; flex-direction: column; gap: 12px; max-height: min(72vh, 760px); overflow: auto; }
.bw-out { border: 1px solid var(--line); border-radius: 7px; padding: 10px 12px; display: flex; flex-direction: column; gap: 10px; background: var(--surface-2); }
.bw-th { display: flex; align-items: center; gap: 8px; font-size: 12.5px; }
.bw-txt { margin: 4px 0 0; font-size: 12.5px; line-height: 1.65; white-space: pre-wrap; color: var(--ink); }
</style>
