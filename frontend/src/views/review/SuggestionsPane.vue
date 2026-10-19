<script setup lang="ts">
/**
 * 审核队列的“建议”页签（REQ-036，预览 DevelopDocs/ui-preview/M6/kb.html 维护员视角）：
 * GET /kb/suggestions?mine=false&status=pending 列出普通用户提交的建议（提出人与所在项目、改动前后、理由）；
 * 采纳 / 驳回用 POST /review/{id}（驳回必须写原因，提出人在“我的建议”里看到）。采纳只记录结论，知识库到对应页面改。
 */
import { onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { errorText, get, post } from '@/api'
import { useAuth } from '@/stores/auth'
import { shortTime } from '@/views/account/account'
import { canReject, diffOf, editLink, kindOf, meaningful, type SuggestionItem } from '@/views/kbsugg/logic'

const emit = defineEmits<{ (e: 'decided', approved: boolean): void }>()
const auth = useAuth()
const items = ref<SuggestionItem[] | null>(null)
const error = ref('')
const actError = ref('')
const busy = ref<number | null>(null)
const rejecting = ref<number | null>(null)
const rejectNote = ref('')

async function load(): Promise<void> {
  error.value = ''
  try {
    items.value = (await get<{ items: SuggestionItem[] }>('/kb/suggestions?mine=false&status=pending')).items
  } catch (e) {
    error.value = errorText(e)
  }
}
onMounted(load)
defineExpose({ load })

async function decide(it: SuggestionItem, approve: boolean): Promise<void> {
  if (!approve && !canReject(rejectNote.value)) return
  busy.value = it.id
  actError.value = ''
  try {
    await post(`/review/${it.id}`, { action: approve ? 'approve' : 'reject', note: approve ? '' : rejectNote.value.trim() })
    rejecting.value = null
    rejectNote.value = ''
    items.value = (items.value ?? []).filter((x) => x.id !== it.id)
    emit('decided', approve)
  } catch (e) {
    actError.value = errorText(e)
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <section class="panel sg-pane" data-testid="review-suggestions">
    <div class="panel-h"><h2>{{ $t('review.tabSugg') }}</h2><span class="meta">{{ $t('review.sg.note') }}</span></div>
    <div v-if="error" class="notice err" style="margin: 12px"><Icon name="err" /><div class="grow">{{ error }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
    <p v-else-if="!items" class="faint" style="padding: 14px 16px">{{ $t('c.loading') }}</p>
    <div v-else-if="!items.length" class="empty" data-testid="review-sg-empty"><p>{{ $t('review.sg.empty') }}</p></div>
    <template v-else>
      <div v-if="actError" class="notice err" style="margin: 12px"><Icon name="err" /><div class="grow">{{ actError }}</div></div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>{{ $t('review.sg.who') }}</th><th>{{ $t('review.sg.target') }}</th><th>{{ $t('review.sg.kind') }}</th><th>{{ $t('review.sg.content') }}</th><th>{{ $t('review.sg.reason') }}</th><th /></tr></thead>
          <tbody>
            <template v-for="it in items" :key="it.id">
              <tr :data-testid="`review-sg-${it.id}`">
                <td>
                  <div class="who">
                    <span class="m6av">{{ (it.source?.user ?? '?').charAt(0).toUpperCase() }}</span>
                    <div><b>{{ it.source?.user ?? '—' }}</b><small class="mono">{{ it.source?.project ?? '' }} · {{ shortTime(it.created_at) }}</small></div>
                  </div>
                </td>
                <td class="mono small">{{ it.target }}</td>
                <td><span class="sugg-kind">{{ $t(`kbsugg.kind.${kindOf(it)}`) }}</span></td>
                <td class="vdiff">
                  <template v-if="meaningful(diffOf(it).current)"><del>{{ diffOf(it).current }}</del> → </template>
                  <ins v-if="diffOf(it).proposed">{{ diffOf(it).proposed }}</ins>
                  <span v-else-if="!meaningful(diffOf(it).current)" class="faint">—</span>
                </td>
                <td class="small" style="max-width: 300px">{{ it.payload?.reason }}</td>
                <td class="right nowrap">
                  <template v-if="auth.isKbEditor">
                    <router-link class="btn btn-sm btn-ghost" :to="editLink(it.target)">{{ $t('review.sg.openEditor') }}</router-link>
                    <button class="btn btn-sm btn-primary" type="button" :disabled="busy === it.id" :data-testid="`review-sg-accept-${it.id}`" @click="decide(it, true)"><Icon name="check" small />{{ $t('review.sg.accept') }}</button>
                    <button class="btn btn-sm" type="button" :data-testid="`review-sg-reject-${it.id}`" @click="rejecting = rejecting === it.id ? null : it.id; rejectNote = ''">{{ $t('review.sg.reject') }}</button>
                  </template>
                </td>
              </tr>
              <tr v-if="rejecting === it.id" class="sg-rej">
                <td colspan="6">
                  <div class="row">
                    <input v-model="rejectNote" class="input" :placeholder="$t('review.sg.rejectPh')" :data-testid="`review-sg-note-${it.id}`" @keydown.enter="decide(it, false)">
                    <button class="btn btn-sm" type="button" @click="rejecting = null">{{ $t('c.cancel') }}</button>
                    <button class="btn btn-sm btn-danger-solid" type="button" :disabled="busy === it.id || !canReject(rejectNote)" :data-testid="`review-sg-confirm-${it.id}`" @click="decide(it, false)">{{ $t('review.sg.confirmReject') }}</button>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.sg-pane { flex: 1; min-height: 0; overflow: auto; }
.who { display: flex; gap: 8px; align-items: center; }
.who small { display: block; color: var(--ink-3); font-size: 11.5px; }
.sg-rej td { background: var(--red-soft); }
.sg-rej .row { gap: 8px; }
.sg-rej .input { flex: 1; }
</style>
