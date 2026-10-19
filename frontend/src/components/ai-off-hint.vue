<script setup lang="ts">
/** AI 不可用时的通用提示（REQ-040）：按原因区分说明与去处——管理员未开放公共接口、所选公共接口被关闭、个人 API 不完整、
 *  自己选了不用、还没有任何接口。reason 不传时用 /summary 的 ai.reason（按当前账号）。 */
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import { useAuth } from '@/stores/auth'
import { useStatus } from '@/stores/status'
import { normReason, reasonTarget, reasonTone, type AiReason } from '@/views/ai/logic'

const props = defineProps<{ reason?: AiReason | string | null; compact?: boolean; noLink?: boolean }>()
const auth = useAuth()
const status = useStatus()
const r = computed(() => normReason(props.reason ?? status.summary?.ai.reason ?? null))
const key = computed(() => r.value ?? 'unknown')
// 全局 API 令牌没有账号，“我的 AI”对它没有意义：给管理员的接口页
const target = computed(() => (auth.me?.via === 'token' ? 'ai-settings' : reasonTarget(r.value, auth.isAdmin)))
</script>

<template>
  <div class="aoh" :class="[reasonTone(r), { compact }]" role="status" :data-testid="`ai-off-${key}`" data-ai-off>
    <Icon :name="reasonTone(r) === 'warn' ? 'warn' : 'info'" />
    <div class="grow">
      <b>{{ $t(`ai-off.${key}.t`) }}</b>
      <span>{{ $t(`ai-off.${key}.d`) }}</span>
      <slot />
    </div>
    <router-link v-if="!noLink || target !== 'my-ai'" class="btn btn-sm" :to="{ name: target }" data-testid="ai-off-link">
      <Icon :name="target === 'ai-settings' ? 'plug' : 'spark'" small />{{ target === 'ai-settings' ? $t('ai-off.toSettings') : $t('ai-off.toMyAi') }}
    </router-link>
  </div>
</template>

<style scoped>
.aoh { display: flex; gap: 12px; align-items: flex-start; padding: 12px 14px; border-radius: var(--r-panel); border: 1px solid var(--line); background: var(--surface-2); color: var(--ink); }
.aoh > .ico { flex: none; margin-top: 2px; color: var(--ink-3); }
.aoh .grow { min-width: 0; }
.aoh .grow b { display: block; margin-bottom: 2px; }
.aoh .grow span { font-size: 12.5px; color: var(--ink-2); }
.aoh.warn { border-color: var(--amber-line); background: var(--amber-soft); }
.aoh.warn > .ico { color: var(--amber-ink); }
.aoh.compact { padding: 8px 10px; gap: 8px; }
.aoh.compact .grow b { display: inline; margin-right: 6px; font-size: 12.5px; }
.aoh .btn { flex: none; }
</style>
