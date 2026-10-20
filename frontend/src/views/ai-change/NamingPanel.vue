<script setup lang="ts">
/**
 * 翻译自定义规则页的“命名映射建议”（M8-4，REQ-032）：选旧设备、新设备（可选）与目标 Profile，AI 按两边的名称风格建议规则；
 * 代码在旧设备上试运行，卡片里列出完整映射表，冲突拒绝、遗漏与没用上的规则提醒；采纳后保存为我的规则集（列表随之刷新）。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AiEntryButton from '@/components/ai-suggest/AiEntryButton.vue'
import AiSuggestPanel from '@/components/ai-suggest/AiSuggestPanel.vue'
import type { Device } from '@/views/devices/logic'
import { scopes } from './logic'
import './ai-change.css'

const props = defineProps<{ devices: Device[]; profiles: { id: string; family: string }[] }>()
const emit = defineEmits<{ changed: [] }>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`ai-change.${k}`, p ?? {})

const src = ref<number | null>(props.devices[0]?.id ?? null)
const dst = ref<number | null>(null)
const to = ref<string>(props.profiles[0]?.id ?? '')
const panel = ref<InstanceType<typeof AiSuggestPanel> | null>(null)
const aiState = ref('loading')
const ready = computed(() => src.value !== null && !!to.value)
const scope = computed(() => (ready.value ? scopes.naming(Number(src.value), to.value) : ''))
const params = computed(() => {
  const p: Record<string, unknown> = { device_id: src.value, to: to.value }
  if (dst.value !== null) p.target_device_id = dst.value
  return p
})
</script>

<template>
  <section class="panel mt16" data-testid="ai-naming">
    <div class="panel-h"><h2>{{ T('namingT') }}</h2><span class="meta">{{ T('namingMeta') }}</span></div>
    <div class="aic-row">
      <label class="small">{{ T('srcDevice') }}
        <select v-model="src" class="select" data-testid="ai-naming-src"><option v-for="d in devices" :key="d.id" :value="d.id">{{ d.name }}</option></select>
      </label>
      <label class="small">{{ T('dstDevice') }}
        <select v-model="dst" class="select" data-testid="ai-naming-dst"><option :value="null">{{ T('none') }}</option><option v-for="d in devices.filter((x) => x.id !== src)" :key="d.id" :value="d.id">{{ d.name }}</option></select>
      </label>
      <label class="small">{{ T('toProfile') }}
        <select v-model="to" class="select" data-testid="ai-naming-to"><option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.id }}</option></select>
      </label>
      <AiEntryButton :skills="['naming-map']" :busy="aiState === 'running'" small @run="panel?.start()" />
    </div>
    <div v-if="ready" style="padding: 0 12px 12px">
      <AiSuggestPanel ref="panel" :key="scope" skill="naming-map" :params="params" :scope="scope" flat @state="aiState = $event" @changed="emit('changed')" />
    </div>
  </section>
</template>
