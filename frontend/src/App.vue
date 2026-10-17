<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
import ptBr from 'element-plus/es/locale/lang/pt-br'
import AppShell from '@/layouts/AppShell.vue'
import { usePrefs } from '@/stores/prefs'

const prefs = usePrefs()
const route = useRoute()
const elLocale = computed(() => ({ 'zh-CN': zhCn, en, 'pt-BR': ptBr })[prefs.lang])
</script>

<template>
  <el-config-provider :locale="elLocale">
    <router-view v-if="route.meta.bare" />
    <AppShell v-else><router-view /></AppShell>
  </el-config-provider>
</template>
