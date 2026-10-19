<script setup lang="ts">
/** 一次调用的详情：输入与回复（均已脱敏）、校验明细、评价与更正。 */
import { onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { errorText, get } from '@/api'
import { shortTime } from '@/views/account/account'
import Bits from './Bits.vue'
import { useT } from './ctx'
import type { RunDetail } from './types'

const props = defineProps<{ sid: string; runId: number }>()
const emit = defineEmits<{ close: [] }>()
const { T, usedBy } = useT()
const run = ref<RunDetail | null>(null)
const err = ref('')
onMounted(async () => {
  try { run.value = await get<RunDetail>(`/ai/skills/${props.sid}/runs/${props.runId}`) } catch (e) { err.value = errorText(e) }
})
const pretty = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v, null, 2))
</script>

<template>
  <div class="modal-back" @click.self="emit('close')">
    <div class="modal" role="dialog" aria-modal="true" style="width: min(820px, 100%)" data-testid="run-dialog">
      <div class="modal-h"><h2>{{ T('runs.detailTitle', { n: runId }) }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="emit('close')"><Icon name="x" /></button></div>
      <div class="modal-b" style="max-height: 70vh; overflow: auto; display: flex; flex-direction: column; gap: 10px">
        <div v-if="err" class="notice err"><Icon name="err" /><div>{{ err }}</div></div>
        <div v-else-if="!run" class="muted">{{ $t('c.loading') }}</div>
        <template v-else>
          <div class="row wrap" style="gap: 8px; align-items: center">
            <Bits kind="ver" :v="run.version" /><Bits kind="vs" :s="run.status" /><span class="uchip">{{ usedBy(run.source) }}</span>
            <span class="small faint">{{ shortTime(run.created_at) }} · {{ run.actor || '—' }} · {{ run.model || '—' }}</span>
          </div>
          <div class="sent"><div class="sh"><b>{{ T('runs.input') }}</b><span class="faint">{{ T('runs.sanitized') }}</span></div><pre>{{ pretty(run.input) }}</pre></div>
          <div class="sent"><div class="sh"><b>{{ T('test.reply') }}</b><span class="ailabel"><Icon name="spark" small />AI</span></div><pre>{{ run.reply || T('runs.noReply') }}</pre></div>
          <div v-if="run.detail" class="sent"><div class="sh"><b>{{ T('runs.detail') }}</b></div><pre>{{ pretty(run.detail) }}</pre></div>
          <div v-if="run.rating || run.correction" class="notice" :class="run.rating === 'up' ? 'info' : 'warn'">
            <Icon :name="run.rating === 'up' ? 'thumbUp' : run.rating === 'down' ? 'thumbDown' : 'pencil'" />
            <div class="grow">
              <b>{{ run.rating ? T(`rate.${run.rating}`) : T('rate.corr') }}</b> · {{ run.feedback_by }} · {{ shortTime(run.feedback_at) }}
              <pre v-if="run.correction" class="mono small" style="margin: 6px 0 0; white-space: pre-wrap">{{ run.correction }}</pre>
            </div>
          </div>
        </template>
      </div>
      <div class="modal-f"><button class="btn" type="button" @click="emit('close')">{{ $t('c.close') }}</button></div>
    </div>
  </div>
</template>
