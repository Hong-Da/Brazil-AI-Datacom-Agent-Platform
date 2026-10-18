<script setup lang="ts">
/** 下载翻译结果：报告（中文 / English 各一份）、译文、含默认值的译文、告警 CSV、接口映射 CSV。 */
import Icon from '@/components/Icon.vue'

defineProps<{ file: string; hasDefaults: boolean; hasMap: boolean }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'dl', k: string): void }>()
</script>

<template>
  <div class="modal-back" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div class="modal" role="dialog" aria-modal="true" style="width: min(640px, 100%)" data-testid="tr-dl-dialog">
      <div class="modal-h"><h2>{{ $t('translate.dl.title') }}</h2><button class="btn btn-ghost btn-icon btn-sm" type="button" :aria-label="$t('c.close')" @click="emit('close')"><Icon name="x" small /></button></div>
      <div class="modal-b">
        <div class="dl-grid">
          <div class="h" /><div class="h">中文</div><div class="h">English</div>
          <div class="rh">{{ $t('translate.dl.report') }}</div>
          <div><a href="#" class="dl-link" data-testid="tr-dl-rep-zh" @click.prevent="emit('dl', 'rep-zh')"><Icon name="file" small />Markdown <small>.md</small></a></div>
          <div><a href="#" class="dl-link" data-testid="tr-dl-rep-en" @click.prevent="emit('dl', 'rep-en')"><Icon name="file" small />Markdown <small>.md</small></a></div>
        </div>
        <div class="sec-k" style="margin-top: 16px">{{ $t('translate.dl.files') }}</div>
        <div class="stack" style="gap: 6px">
          <a href="#" class="dl-link" data-testid="tr-dl-cfg" @click.prevent="emit('dl', 'cfg')"><Icon name="download" small />{{ $t('translate.dl.cfg') }} <small class="mono">{{ file }}</small></a>
          <a v-if="hasDefaults" href="#" class="dl-link" @click.prevent="emit('dl', 'full')"><Icon name="download" small />{{ $t('translate.dl.full') }}</a>
          <a href="#" class="dl-link" data-testid="tr-dl-warn" @click.prevent="emit('dl', 'warn')"><Icon name="download" small />{{ $t('translate.dl.warn') }} <small class="mono">warnings.csv</small></a>
          <a v-if="hasMap" href="#" class="dl-link" @click.prevent="emit('dl', 'map')"><Icon name="download" small />{{ $t('translate.dl.map') }} <small class="mono">interface-map.csv</small></a>
        </div>
        <p class="small faint mt12">{{ $t('translate.dl.note') }}</p>
      </div>
      <div class="modal-f"><button class="btn btn-primary" type="button" @click="emit('close')">{{ $t('c.done') }}</button></div>
    </div>
  </div>
</template>
