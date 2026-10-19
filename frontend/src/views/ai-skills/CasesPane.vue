<script setup lang="ts">
/** 回归集（失败案例自动入集，按输入去重）与候选示例（校验通过且点赞）：删除、把候选加入示例（形成新版本并生效）。 */
import { computed, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { errorText, del, post } from '@/api'
import { shortTime } from '@/views/account/account'
import Bits from './Bits.vue'
import RunModal from './RunModal.vue'
import { useSkillCtx, useT } from './ctx'
import { caseStatus, inputSummary, reasonTone } from './logic'
import type { CaseRow } from './types'

const { detail, cases, loadCases, reload, flash, goTab } = useSkillCtx()
const { T } = useT()
const delOpen = ref<CaseRow | null>(null)
const busy = ref<number | null>(null)
const runOpen = ref<number | null>(null)
const reg = computed(() => cases.value?.regression ?? [])
const cand = computed(() => cases.value?.candidates ?? [])
onMounted(loadCases)

function reasonText(r: string): string {
  return ['rejected', 'corrected', 'down', 'correction', 'manual', 'up'].includes(r) ? T(`reason.${r}`) : r
}
async function doDelete(): Promise<void> {
  const c = delOpen.value
  delOpen.value = null
  if (!c || !detail.value) return
  busy.value = c.id
  try {
    await del(`/ai/skills/${detail.value.id}/cases/${c.id}`)
    await loadCases()
    flash(T('cases.deleted'))
  } catch (e) { flash(errorText(e)) } finally { busy.value = null }
}
async function toExample(c: CaseRow): Promise<void> {
  if (!detail.value) return
  busy.value = c.id
  try {
    const r = await post<{ version?: string }>(`/ai/skills/${detail.value.id}/cases/${c.id}/example`)
    await Promise.all([loadCases(), reload(false)])
    flash(T('cases.exampleAdded', { v: r.version ?? detail.value.active }))
  } catch (e) { flash(errorText(e)) } finally { busy.value = null }
}
</script>

<template>
  <div v-if="detail" data-testid="sk-cases">
    <div class="cases-note" style="margin-bottom: 12px">
      <span><Icon name="info" small />{{ T('cases.note1') }}</span>
      <span><Icon name="dna" small />{{ T('cases.note2') }}</span>
    </div>
    <section class="panel">
      <div class="panel-h"><h2>{{ T('cases.reg') }} <span class="faint small">{{ reg.length }}</span></h2></div>
      <div v-if="!reg.length" class="empty" data-testid="cases-reg-empty">
        <h3>{{ T('cases.regEmpty') }}</h3><p>{{ T('cases.regEmptyText') }}</p>
        <button class="btn btn-sm" type="button" @click="goTab('stats')"><Icon name="flask" small />{{ T('tab.stats') }}</button>
      </div>
      <div v-else class="tbl-wrap">
        <table class="tbl cases-tbl" data-testid="cases-reg">
          <thead><tr><th>#</th><th>{{ T('cases.input') }}</th><th>{{ T('cases.reason') }}</th><th>{{ T('cases.latest') }}</th><th>{{ T('cases.added') }}</th><th>{{ T('cases.run') }}</th><th /></tr></thead>
          <tbody>
            <tr v-for="c in reg" :key="c.id" :data-case="c.id">
              <td class="mono small">{{ c.id }}</td>
              <td><div class="q">{{ inputSummary(c.input) }}</div><div v-if="c.expect" class="corr"><Icon name="pencil" small />{{ c.expect }}</div></td>
              <td><span class="tag" :class="reasonTone(c.reason)">{{ reasonText(c.reason) }}</span></td>
              <td><Bits kind="vs" :s="caseStatus(c)" /></td>
              <td class="small nowrap">{{ shortTime(c.created_at) }}<div class="faint">{{ c.created_by }}</div></td>
              <td class="mono small"><button v-if="c.run_id" class="link-btn" type="button" @click="runOpen = c.run_id">#{{ c.run_id }}</button><span v-else class="faint">—</span></td>
              <td class="right"><button class="btn btn-sm btn-ghost btn-icon" type="button" :disabled="busy === c.id" :title="T('cases.remove')" :aria-label="T('cases.remove')" data-testid="case-del" @click="delOpen = c"><Icon name="trash" small /></button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    <section class="panel mt12">
      <div class="panel-h"><h2>{{ T('cases.cand') }} <span class="faint small">{{ cand.length }}</span></h2><span class="meta">{{ T('cases.candMeta') }}</span></div>
      <div v-if="!cand.length" class="panel-b small faint">{{ T('cases.candEmpty') }}</div>
      <div v-else class="tbl-wrap">
        <table class="tbl cases-tbl" data-testid="cases-cand">
          <thead><tr><th>{{ T('cases.input') }}</th><th>{{ T('test.reply') }}</th><th>{{ T('cases.run') }}</th><th /></tr></thead>
          <tbody>
            <tr v-for="c in cand" :key="c.id" :data-case="c.id">
              <td><div class="q">{{ inputSummary(c.input) }}</div></td>
              <td><div class="q">{{ c.expect || c.reply }}</div></td>
              <td class="small nowrap"><button v-if="c.run_id" class="link-btn mono" type="button" @click="runOpen = c.run_id">#{{ c.run_id }}</button><div class="faint">{{ shortTime(c.created_at) }}</div></td>
              <td class="right nowrap">
                <button class="btn btn-sm" type="button" :disabled="busy === c.id" data-testid="case-to-example" @click="toExample(c)"><Icon name="plus" small />{{ T('cases.toExample') }}</button>
                {{ ' ' }}<button class="btn btn-sm btn-ghost btn-icon" type="button" :disabled="busy === c.id" :title="$t('c.delete')" :aria-label="$t('c.delete')" @click="delOpen = c"><Icon name="trash" small /></button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="delOpen" class="modal-back" @click.self="delOpen = null">
      <div class="modal" role="dialog" aria-modal="true" style="width: min(520px, 100%)" data-testid="case-del-dialog">
        <div class="modal-h"><h2>{{ T('cases.delTitle', { n: delOpen.id }) }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="delOpen = null"><Icon name="x" /></button></div>
        <div class="modal-b"><p>{{ T('cases.delText') }}</p></div>
        <div class="modal-f"><button class="btn" type="button" @click="delOpen = null">{{ $t('c.cancel') }}</button><button class="btn btn-danger" type="button" data-testid="case-del-ok" @click="doDelete">{{ $t('c.delete') }}</button></div>
      </div>
    </div>
    <RunModal v-if="runOpen !== null" :sid="detail.id" :run-id="runOpen" @close="runOpen = null" />
  </div>
</template>
