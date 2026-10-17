<script setup lang="ts">
import { LANGS } from '@/i18n'
import { usePrefs } from '@/stores/prefs'
const prefs = usePrefs()
</script>

<template>
  <el-select v-model="prefs.lang" size="small" style="width: 170px" :aria-label="$t('shell.language')" data-testid="lang-switch">
    <el-option v-for="l in LANGS" :key="l.code" :value="l.code" :label="l.label" />
  </el-select>
</template>
