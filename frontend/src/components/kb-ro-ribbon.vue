<script setup lang="ts">
/**
 * 知识库只读说明（REQ-036，预览 DevelopDocs/ui-preview/M6/kb.html 的 .ro-ribbon）：只对不能修改知识库的账号显示。
 * full：Schema 视图用，带“我的建议 N”按钮（打开我的建议列表）；其他知识库页面显示短说明并链接到 Schema 视图提建议。
 */
import { onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import KbMySuggestions from '@/components/kb-my-suggestions.vue'
import { get } from '@/api'
import { useAuth } from '@/stores/auth'

const props = defineProps<{ full?: boolean }>()
const auth = useAuth()
const count = ref<number | null>(null)
const showMine = ref(false)

async function loadCount(): Promise<void> {
  try { count.value = (await get<{ items: unknown[] }>('/kb/suggestions')).items.length } catch { count.value = null }
}
onMounted(() => { if (props.full && !auth.isKbEditor) void loadCount() })
defineExpose({ reload: loadCount })
</script>

<template>
  <template v-if="!auth.isKbEditor">
    <div class="ro-ribbon" data-testid="kb-ro-ribbon">
      <Icon name="lock" small />
      <div class="grow">{{ full ? $t('kbsugg.ribbon') : $t('kbsugg.ribbonShort') }}</div>
      <button v-if="full" class="btn btn-sm" type="button" data-testid="kb-open-mine" @click="showMine = true">
        {{ count === null ? $t('kbsugg.mine') : $t('kbsugg.mineCount', { n: count }) }}
      </button>
      <router-link v-else class="btn btn-sm" :to="{ name: 'schema-view' }"><Icon name="chat" small />{{ $t('kbsugg.button') }}</router-link>
    </div>
    <div v-if="showMine" class="modal-back" data-testid="kb-mine-modal" @click.self="showMine = false" @keydown.esc="showMine = false">
      <div class="modal" style="width: min(900px, 100%)" role="dialog" aria-modal="true">
        <div class="modal-h">
          <h2>{{ $t('kbsugg.mine') }}</h2>
          <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="showMine = false"><Icon name="x" /></button>
        </div>
        <div class="modal-b" style="padding: 0"><KbMySuggestions embedded @count="count = $event" /></div>
      </div>
    </div>
  </template>
</template>
