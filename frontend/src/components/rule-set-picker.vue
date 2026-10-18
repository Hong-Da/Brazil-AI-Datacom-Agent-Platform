<script setup lang="ts">
/** 翻译规则集选择框（REQ-032）：翻译页、割接迁移页共用。值为规则集编号，空串表示不使用。 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { get } from '@/api'
import { titleOf, type RuleSetInfo } from '@/views/translate-rules/logic'

const props = defineProps<{ modelValue: string; testid?: string }>()
const emit = defineEmits<{ 'update:modelValue': [string] }>()
const { locale } = useI18n()

const items = ref<RuleSetInfo[]>([])
const failed = ref(false)
async function load(): Promise<void> {
  try {
    items.value = (await get<{ items: RuleSetInfo[] }>('/translate-rules')).items.filter((i) => i.valid !== false)
    failed.value = false
  } catch {
    failed.value = true
  }
}
const builtin = computed(() => items.value.filter((i) => i.builtin))
const mine = computed(() => items.value.filter((i) => !i.builtin))
const value = computed({ get: () => props.modelValue, set: (v: string) => emit('update:modelValue', v) })
const label = (i: RuleSetInfo) => `${titleOf(i, String(locale.value))} (${i.id})`
onMounted(load)
defineExpose({ reload: load })
</script>

<template>
  <span class="rsp">
    <label class="rsp-l" :for="`${testid ?? 'rsp'}-sel`"><Icon name="pencil" small />{{ $t('translate-rules.picker') }}</label>
    <select :id="`${testid ?? 'rsp'}-sel`" v-model="value" class="select" :data-testid="testid ?? 'rule-set'">
      <option value="">{{ $t('translate-rules.none') }}</option>
      <optgroup v-if="builtin.length" :label="$t('translate-rules.builtin')">
        <option v-for="i in builtin" :key="i.id" :value="i.id">{{ label(i) }}</option>
      </optgroup>
      <optgroup v-if="mine.length" :label="$t('translate-rules.mine')">
        <option v-for="i in mine" :key="i.id" :value="i.id">{{ label(i) }}</option>
      </optgroup>
    </select>
    <router-link v-if="value" class="btn btn-ghost btn-xs" :to="{ name: 'translate-rules', query: { id: value } }" :data-testid="`${testid ?? 'rule-set'}-edit`">{{ $t('translate-rules.edit') }}</router-link>
    <router-link class="btn btn-ghost btn-xs" :to="{ name: 'translate-rules', query: { new: '1' } }" :data-testid="`${testid ?? 'rule-set'}-new`"><Icon name="plus" small />{{ $t('translate-rules.new') }}</router-link>
    <span v-if="failed" class="small faint">{{ $t('translate-rules.loadFailed') }}</span>
  </span>
</template>

<style scoped>
.rsp { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; min-width: 0; }
.rsp-l { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--ink-2); white-space: nowrap; }
.rsp .select { min-width: 200px; max-width: 320px; }
</style>
