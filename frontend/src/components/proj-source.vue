<script setup lang="ts">
/**
 * 设备来源与版本标记（REQ-035）：私有 / 公共引用；引用的“跟随最新 · vN”或“固定在 vN”，公共库有新版本时琥珀提示。
 * seq：当前版本的序号（vN）；latestSeq：公共库最新版本的序号（固定且有新版本时显示）。
 */
import Icon from '@/components/Icon.vue'

defineProps<{
  source?: string | null
  policy?: string | null
  seq?: number | null
  latestSeq?: number | null
  newer?: boolean
  noMark?: boolean
}>()
</script>

<template>
  <span class="vcell">
    <template v-if="!noMark">
      <span v-if="source === 'public'" class="srcmark ref" :title="$t('proj.src.publicTip')" data-testid="src-public"><Icon name="link" small />{{ $t('proj.src.public') }}</span>
      <span v-else class="srcmark priv" :title="$t('proj.src.privateTip')" data-testid="src-private"><Icon name="server" small />{{ $t('proj.src.private') }}</span>
      &nbsp;
    </template>
    <template v-if="source === 'public'">
      <span v-if="policy === 'pin'" class="verchip pin" data-testid="ver-pin"><Icon name="pin" small />{{ $t('proj.ver.pinned') }}<template v-if="seq"> v{{ seq }}</template></span>
      <span v-else class="verchip follow" data-testid="ver-follow"><Icon name="refresh" small />{{ $t('proj.ver.follow') }}<template v-if="seq"> · v{{ seq }}</template></span>
      <span v-if="newer" class="newver" :title="$t('proj.ver.newer')" data-testid="ver-newer">{{ latestSeq ? `v${latestSeq}` : $t('proj.ver.newer') }}</span>
    </template>
    <span v-else-if="seq" class="verchip priv">v{{ seq }}</span>
  </span>
</template>
