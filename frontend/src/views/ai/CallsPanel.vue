<script setup lang="ts">
/** AI 调用记录：管理员看全部（带用户与接口列，可按用户 / 接口 / 任务筛选）；“我的 AI”只看自己的（mine）。 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { errorText, get } from '@/api'
import Icon from '@/components/Icon.vue'
import { fmtTime } from '../ingest/logic'
import { distinct, filterCalls, type AiCall } from './logic'

const props = defineProps<{ mine?: boolean; title: string; foot?: string; connectionId?: number | null; limit?: number }>()
const emit = defineEmits<{ loaded: [calls: AiCall[]] }>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`ai-settings.${k}`, p ?? {})

const calls = ref<AiCall[]>([])
const err = ref('')
const loading = ref(false)
const fUser = ref('')
const fConn = ref('')
const fTask = ref('')

async function load(): Promise<void> {
  loading.value = true
  err.value = ''
  try {
    const q = props.connectionId != null ? `&connection_id=${props.connectionId}` : ''
    calls.value = (await get<{ calls: AiCall[] }>(`/ai/calls?limit=${props.limit ?? 1000}${q}`)).calls
    emit('loaded', calls.value)
  } catch (e) {
    err.value = errorText(e)
  } finally {
    loading.value = false
  }
}
defineExpose({ load })

const users = computed(() => distinct(calls.value, 'user'))
const conns = computed(() => distinct(calls.value, 'connection'))
const tasks = computed(() => distinct(calls.value, 'task'))
const shown = computed(() => filterCalls(calls.value, { user: fUser.value, connection: fConn.value, task: fTask.value }).slice(0, 300))
const taskLabel = (k: string) => (['extract', 'merge', 'ask', 'generate', 'test'].includes(k) ? T(`task_${k}`) : k)
const connLabel = (c: string) => (c === 'personal' ? T('personal') : c)

onMounted(load)
</script>

<template>
  <section class="panel" :data-testid="mine ? 'my-ai-calls' : 'ai-calls'">
    <div class="panel-h">
      <h2>{{ title }}</h2>
      <select v-if="!mine" v-model="fUser" class="select hsel" data-testid="ai-calls-user"><option value="">{{ T('allUsers') }}</option><option v-for="u in users" :key="u" :value="u">{{ u }}</option></select>
      <select v-if="connectionId == null" v-model="fConn" class="select hsel" data-testid="ai-calls-conn"><option value="">{{ T('allConns') }}</option><option v-for="c in conns" :key="c" :value="c">{{ connLabel(c) }}</option></select>
      <select v-model="fTask" class="select hsel" data-testid="ai-calls-filter"><option value="">{{ T('allTasks') }}</option><option v-for="k in tasks" :key="k" :value="k">{{ taskLabel(k) }}</option></select>
      <button class="btn btn-sm btn-icon" :title="$t('c.refresh')" :aria-label="$t('c.refresh')" data-testid="ai-calls-refresh" @click="load"><Icon name="refresh" small /></button>
    </div>
    <div v-if="err" class="empty small"><p>{{ err }}</p><button class="btn btn-sm" @click="load">{{ $t('c.retry') }}</button></div>
    <div v-else-if="loading && !calls.length" class="empty small">{{ $t('c.loading') }}</div>
    <div v-else-if="!calls.length" class="empty small">{{ T('noCalls') }}</div>
    <div v-else class="tbl-wrap" style="max-height: 380px">
      <table class="tbl compact" data-testid="ai-calls-table">
        <thead>
          <tr>
            <th>{{ T('time') }}</th><th v-if="!props.mine">{{ T('user') }}</th><th v-if="connectionId == null">{{ T('conn') }}</th><th>{{ T('task') }}</th><th>{{ T('modelCol') }}</th>
            <th class="num">{{ T('in') }}</th><th class="num">{{ T('out') }}</th><th>{{ T('result') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in shown" :key="c.id">
            <td class="nowrap faint">{{ fmtTime(c.created_at) }}</td>
            <td v-if="!props.mine"><span class="who"><span class="av">{{ (c.user || '?').charAt(0).toUpperCase() }}</span>{{ c.user || '—' }}</span></td>
            <td v-if="connectionId == null" class="nowrap"><span class="cc" :class="{ personal: c.connection === 'personal' }"><Icon v-if="c.connection === 'personal'" name="lock" small />{{ c.connection ? connLabel(c.connection) : '—' }}</span></td>
            <td>{{ taskLabel(c.task) }}</td>
            <td class="nowrap"><span class="small">{{ c.provider }}</span> <span class="mono small faint">{{ c.model }}</span></td>
            <td class="num">{{ (c.tokens_in ?? 0).toLocaleString('en-US') }}</td>
            <td class="num">{{ (c.tokens_out ?? 0).toLocaleString('en-US') }}</td>
            <td class="nowrap">
              <span v-if="c.status === 'ok'" class="tag pass">{{ T('callOk') }}</span>
              <span v-else class="tag error" :title="c.error ?? ''">{{ T('callErr') }}</span>
              <router-link v-if="c.review_item_id && !mine" class="mono small" :to="{ name: 'review' }"> #{{ c.review_item_id }}</router-link>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="foot" class="panel-f small faint"><Icon name="info" small /><span>{{ foot }}</span></div>
  </section>
</template>

<style scoped>
.hsel { width: auto; height: 28px; max-width: 160px; }
.who { display: inline-flex; gap: 6px; align-items: center; }
.who .av { width: 18px; height: 18px; border-radius: 50%; background: var(--surface-3); color: var(--ink-2); display: inline-flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 600; }
.cc { display: inline-flex; gap: 5px; align-items: center; font-size: 12px; }
.cc.personal { color: var(--teal-ink); }
</style>
