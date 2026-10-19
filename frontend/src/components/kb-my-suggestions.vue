<script setup lang="ts">
/** “我的建议”（REQ-036）：GET /kb/suggestions（只看自己提的），显示改动前后、状态与驳回原因。reload() 供父组件提交后刷新。 */
import { onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { errorText, get } from '@/api'
import { shortTime } from '@/views/account/account'
import { diffOf, kindOf, meaningful, statusTag, type SuggestionItem } from '@/views/kbsugg/logic'

defineProps<{ embedded?: boolean }>()
const emit = defineEmits<{ (e: 'count', n: number): void }>()
const items = ref<SuggestionItem[] | null>(null)
const error = ref('')

async function reload(): Promise<void> {
  error.value = ''
  try {
    const d = await get<{ items: SuggestionItem[] }>('/kb/suggestions')
    items.value = [...d.items].sort((a, b) => b.id - a.id)
    emit('count', items.value.length)
  } catch (e) {
    error.value = errorText(e)
  }
}
onMounted(reload)
defineExpose({ reload })
</script>

<template>
  <section id="kb-mine" :class="['panel', { 'is-embedded': embedded }]" data-testid="kb-my-suggestions">
    <div class="panel-h"><h2 v-if="!embedded">{{ $t('kbsugg.mine') }}</h2><span v-else class="grow" /><button class="btn btn-sm btn-ghost" type="button" :title="$t('c.refresh')" @click="reload"><Icon name="refresh" small /></button></div>
    <div v-if="error" class="notice err" style="margin: 12px"><Icon name="err" /><div class="grow">{{ error }}</div><button class="btn btn-sm" type="button" @click="reload">{{ $t('c.retry') }}</button></div>
    <p v-else-if="!items" class="faint" style="padding: 12px 16px">{{ $t('c.loading') }}</p>
    <p v-else-if="!items.length" class="faint" style="padding: 12px 16px" data-testid="kb-my-empty">{{ $t('kbsugg.mineEmpty') }}</p>
    <div v-else class="tbl-wrap">
      <table class="tbl">
        <thead><tr><th>{{ $t('kbsugg.col.target') }}</th><th>{{ $t('kbsugg.col.kind') }}</th><th>{{ $t('kbsugg.col.content') }}</th><th>{{ $t('kbsugg.col.at') }}</th><th>{{ $t('kbsugg.col.status') }}</th></tr></thead>
        <tbody>
          <tr v-for="it in items" :key="it.id" :data-testid="`kb-my-${it.id}`">
            <td class="mono small">{{ it.target }}</td>
            <td><span class="sugg-kind">{{ $t(`kbsugg.kind.${kindOf(it)}`) }}</span></td>
            <td class="vdiff">
              <template v-if="meaningful(diffOf(it).current)"><del>{{ diffOf(it).current }}</del> → </template>
              <ins v-if="diffOf(it).proposed">{{ diffOf(it).proposed }}</ins>
              <div class="small muted" style="font-family: var(--font-ui)">{{ it.payload?.reason }}</div>
            </td>
            <td class="small muted nowrap">{{ shortTime(it.created_at) }}</td>
            <td>
              <span :class="['tag', statusTag(it.status).cls]">{{ $t(`kbsugg.${statusTag(it.status).key}`) }}</span>
              <div v-if="it.status === 'rejected' && it.note" class="small muted">{{ $t('kbsugg.rejectedWhy', { n: it.note }) }}</div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.is-embedded { border: 0; border-radius: 0; box-shadow: none; }
</style>
