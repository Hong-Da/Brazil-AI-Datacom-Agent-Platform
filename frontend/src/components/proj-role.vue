<script setup lang="ts">
/** 项目角色标记（属主 / 可编辑 / 只读 / 管理员访问），样式见 styles/m6.css 的 .rolechip。 */
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'

const props = defineProps<{ role: string | null | undefined }>()
const ICON: Record<string, string> = { owner: 'user', edit: 'pencil', read: 'eye', admin: 'shield' }
const known = computed(() => (props.role && ICON[props.role] ? props.role : null))
</script>

<template>
  <span v-if="known" :class="['rolechip', `r-${known}`]" :data-testid="`role-${known}`">
    <Icon :name="ICON[known]" small />{{ $t(`proj.role.${known}`) }}
  </span>
</template>
