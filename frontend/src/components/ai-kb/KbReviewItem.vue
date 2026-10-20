<script setup lang="ts">
/**
 * 审核队列里 AI 建议采纳后的知识库草稿（M8-5）：
 * - rule：规则 YAML（来自规范条款），可改 YAML 后通过（edited.yaml）；
 * - unknown_card：未识别行归因的命令卡（缺命令卡新建 / 版本差异与写法变体改已有卡），可改字段（edited.card）；
 * - card_maps：命令卡 → Schema 节点的映射，可改映射表（edited.maps）。
 * 父组件（ReviewDetail）通过时调用 edited() 取修改内容；返回 { error } 时不提交。
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { parseMaps, ucardEdited, ucardForm, UCARD_FIELDS, type ReviewItem, type UcardField } from '@/views/review/logic'

const props = defineProps<{ item: ReviewItem; editing: boolean }>()
const { t } = useI18n()

const p = computed(() => (props.item.payload ?? {}) as Record<string, unknown>)
const card = computed(() => (p.value.card && typeof p.value.card === 'object' ? p.value.card : {}) as Record<string, unknown>)
const cause = computed(() => String(p.value.cause ?? 'missing'))
const maps = computed(() => (p.value.maps && typeof p.value.maps === 'object' ? p.value.maps : {}) as Record<string, unknown>)
const mapRows = computed(() => Object.entries(maps.value).map(([node, e]) => ({ node, expr: typeof e === 'string' ? e : JSON.stringify(e) })))
const cardText = computed(() => Object.entries(card.value)
  .filter(([, v]) => v !== null && v !== undefined && v !== '')
  .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`).join('\n'))
const skill = computed(() => String(props.item.source?.skill ?? ''))
const sugId = computed(() => p.value.ai_suggestion ?? props.item.source?.suggestion_id ?? null)

const yaml = ref('')
const form = ref<Record<UcardField, string>>(ucardForm({}))
const mapsText = ref('')

function reset(): void {
  yaml.value = String(p.value.yaml ?? '')
  form.value = ucardForm(card.value)
  mapsText.value = JSON.stringify(maps.value, null, 2)
}
watch(() => [props.item.id, props.editing], reset, { immediate: true })

/** 通过时的修改内容：null 表示没改；{ error } 表示不能提交。 */
function edited(): Record<string, unknown> | null | { error: string } {
  if (!props.editing) return null
  const k = props.item.kind
  if (k === 'rule') {
    if (!yaml.value.trim()) return { error: t('kb-ai.rv.yamlEmpty') }
    return yaml.value === String(p.value.yaml ?? '') ? null : { yaml: yaml.value }
  }
  if (k === 'unknown_card') {
    const r = ucardEdited(card.value, form.value, cause.value === 'missing')
    if (r === 'incomplete') return { error: t('kb-ai.rv.cardIncomplete') }
    return r ? { card: r } : null
  }
  if (k === 'card_maps') {
    const r = parseMaps(mapsText.value, maps.value)
    if ('error' in r) return { error: t(`kb-ai.rv.maps_${r.error}`) }
    return r.maps ? { maps: r.maps } : null
  }
  return null
}
defineExpose({ edited })
</script>

<template>
  <div class="kri" data-testid="review-ai-kb" :data-kind="item.kind">
    <div class="ai-src small">
      <span class="tag t-violet">{{ $t('kb-ai.rv.fromAi') }}</span>
      <span v-if="skill" class="mono">{{ skill }}</span>
      <span v-if="sugId != null" class="faint">{{ $t('kb-ai.rv.sugId', { id: sugId }) }}</span>
    </div>

    <!-- 规则草稿 -->
    <template v-if="item.kind === 'rule'">
      <template v-if="p.clause">
        <div class="section-t">{{ $t('kb-ai.rv.clause') }}</div>
        <div class="docq">{{ p.clause }}</div>
      </template>
      <div class="section-t">{{ $t('kb-ai.rv.ruleYaml') }}</div>
      <textarea v-if="editing" v-model="yaml" class="textarea mono yaml-ed" spellcheck="false" data-testid="review-rule-yaml-edit" />
      <pre v-else class="block mono" data-testid="review-rule-yaml">{{ p.yaml }}</pre>
      <p class="small faint">{{ $t('kb-ai.rv.ruleHint') }}</p>
    </template>

    <!-- 未识别行归因的命令卡 -->
    <template v-else-if="item.kind === 'unknown_card'">
      <dl class="kv">
        <dt>{{ $t('kb-ai.rv.cause') }}</dt><dd><span class="tag">{{ $t(`ai-suggest.kb.cause.${cause}`) }}</span></dd>
        <template v-if="p.base"><dt>{{ $t('kb-ai.rv.base') }}</dt><dd class="mono">{{ p.base }}</dd></template>
        <template v-if="p.domain"><dt>{{ $t('kb-ai.rv.domain') }}</dt><dd class="mono">{{ p.domain }}</dd></template>
      </dl>
      <div class="section-t">{{ cause === 'missing' ? $t('kb-ai.rv.newCard') : $t('kb-ai.rv.changeCard') }}</div>
      <div v-if="editing" class="form-grid" data-testid="review-ucard-edit">
        <div v-for="k in UCARD_FIELDS" :key="k" :class="['field', { span2: k === 'syntax' || k === 'undo' }]">
          <label>{{ $t(`kb-ai.rv.f_${k}`) }}</label>
          <input v-model="form[k]" class="input mono" spellcheck="false" :disabled="k === 'id' && cause !== 'missing'" :data-testid="`review-ucard-${k}`" />
        </div>
        <p class="small faint span2">{{ $t('kb-ai.rv.cardHint') }}</p>
      </div>
      <pre v-else class="block mono" data-testid="review-ucard">{{ cardText }}</pre>
    </template>

    <!-- 映射建议 -->
    <template v-else-if="item.kind === 'card_maps'">
      <dl class="kv"><dt>{{ $t('kb-ai.rv.card') }}</dt><dd class="mono">{{ item.target }}</dd></dl>
      <div class="section-t">{{ $t('kb-ai.rv.maps') }}</div>
      <template v-if="editing">
        <textarea v-model="mapsText" class="textarea mono yaml-ed" spellcheck="false" data-testid="review-maps-edit" />
        <p class="small faint">{{ $t('kb-ai.rv.mapsHint') }}</p>
      </template>
      <table v-else class="tbl compact" data-testid="review-maps-table">
        <thead><tr><th>{{ $t('kb-ai.rv.node') }}</th><th>{{ $t('kb-ai.rv.expr') }}</th></tr></thead>
        <tbody><tr v-for="r in mapRows" :key="r.node"><td class="mono small">{{ r.node }}</td><td class="mono small">{{ r.expr }}</td></tr></tbody>
      </table>
    </template>
  </div>
</template>

<style scoped>
.kri { display: flex; flex-direction: column; gap: 8px; margin-top: 14px; }
.ai-src { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.section-t { margin-top: 6px; }
.docq { padding: 8px 10px; border-left: 3px solid var(--line-strong); background: var(--surface-2); font-size: 12px; color: var(--ink-2); white-space: pre-wrap; }
.block { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.yaml-ed { width: 100%; min-height: 220px; resize: vertical; }
</style>
