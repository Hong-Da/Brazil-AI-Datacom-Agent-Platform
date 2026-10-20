<script setup lang="ts">
/**
 * 变化解读的覆盖核对条（M8-3，预览 M8/analysis.html 的 covbar）：GET …/ai/suggestions/coverage 由代码算出
 * 有多少差异已归入意图、哪些没有被任何意图解释到。父页面在建议变化（changed）后调用 reload()，
 * 用 loaded 事件拿到结果给差异表打标；点没被解释的条目发 jump（页面定位到对应行）。
 */
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { get } from '@/api'
import { useProject } from '@/stores/project'
import { projectPath, query, type Coverage, type CoverageItem } from './logic'
import './ai-suggest.css'

const props = defineProps<{ skill: string; scope: string }>()
const emit = defineEmits<{ loaded: [cov: Coverage | null]; jump: [item: CoverageItem] }>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`ai-suggest.${k}`, p ?? {})
const project = useProject()
const cov = ref<Coverage | null>(null)

async function reload(): Promise<void> {
  try {
    cov.value = await get<Coverage>(projectPath(project.ref ?? '', `/ai/suggestions/coverage${query({ skill: props.skill, scope: props.scope })}`))
  } catch {
    cov.value = null
  }
  emit('loaded', cov.value)
}
watch(() => props.scope, () => void reload())
onMounted(reload)
defineExpose({ reload })
</script>

<template>
  <div class="covbar" data-testid="ai-cov">
    <template v-if="cov && cov.batch_id && cov.total">
      <span class="vchip" :class="cov.uncovered.length ? 'warn' : 'pass'"><Icon :name="cov.uncovered.length ? 'warn' : 'ok'" small />{{ T('cov.k') }}</span>
      <span>{{ T('cov.n', { a: cov.covered.length, b: cov.total }) }}<template v-if="!cov.uncovered.length">；{{ T('cov.all') }}</template></span>
      <span v-if="cov.uncovered.length" class="un" data-testid="ai-cov-uncovered">
        {{ T('cov.un') }}
        <button v-for="u in cov.uncovered" :key="u.id" type="button" class="aref" :title="u.node ?? ''" @click="emit('jump', u)">{{ u.label || u.id }}</button>
      </span>
      <span v-if="cov.uncovered.length" class="faint">{{ T('cov.hint') }}</span>
    </template>
    <span v-else class="faint">{{ T('cov.idle') }}</span>
  </div>
</template>

<style scoped>
.covbar { display: flex; gap: 6px 10px; align-items: center; padding: 8px 12px; border: 1px solid var(--line); border-radius: var(--r-panel); background: var(--surface); font-size: 12px; color: var(--ink-2); flex-wrap: wrap; }
.covbar .un { display: inline-flex; gap: 4px; flex-wrap: wrap; align-items: center; }
.covbar .aref { font: 11.5px var(--font-mono); }
</style>
