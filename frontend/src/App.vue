<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
import ptBr from 'element-plus/es/locale/lang/pt-br'
import AppShell from '@/layouts/AppShell.vue'
import { usePrefs } from '@/stores/prefs'
import { startPrefsSync } from '@/stores/prefs-sync'

const prefs = usePrefs()
startPrefsSync() // 登录后语言、主题、显示风格、图标风格随账号保存（REQ-047）
const route = useRoute()
const elLocale = computed(() => ({ 'zh-CN': zhCn, en, 'pt-BR': ptBr })[prefs.lang])
// M9：换网络时页面重新加载（同一页面组件只换了网址里的网络参数时 vue-router 会复用组件）
const netKey = computed(() => String(route.params.network ?? ''))
</script>

<template>
  <el-config-provider :locale="elLocale">
    <router-view v-if="route.meta.bare" />
    <AppShell v-else><router-view v-slot="{ Component }"><component :is="Component" :key="netKey" /></router-view></AppShell>
  </el-config-provider>
</template>
