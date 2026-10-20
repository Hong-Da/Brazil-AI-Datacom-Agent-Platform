<script setup lang="ts">
/** 网络标签（M9）：识别色色块 + 名称；给 to 时是链接（跳到那个网络）。默认网络的中文默认名称按当前语言显示。 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RouteLocationRaw } from 'vue-router'
import { colorClass, netName, type NetBrief } from '@/views/networks/logic'

const props = defineProps<{ net: Pick<NetBrief, 'name' | 'color' | 'default'> & { slug?: string }; to?: RouteLocationRaw; cur?: boolean }>()
const { t } = useI18n()
const label = computed(() => netName(props.net, t('net.defaultName')))
const title = computed(() => (props.net.default ? `${label.value}${t('net.defaultSuffix')}` : label.value))
</script>

<template>
  <router-link v-if="to" :to="to" :class="['nw-chip', colorClass(net.color), { 'is-cur': cur }]" :title="title"><i class="nw-sq" /><span>{{ label }}</span></router-link>
  <span v-else :class="['nw-chip', colorClass(net.color), { 'is-cur': cur }]" :title="title"><i class="nw-sq" /><span>{{ label }}</span></span>
</template>
