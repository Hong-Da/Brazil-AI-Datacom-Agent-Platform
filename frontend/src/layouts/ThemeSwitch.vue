<script setup lang="ts">
import { usePrefs } from '@/stores/prefs'
const prefs = usePrefs()
</script>

<template>
  <el-radio-group v-model="prefs.theme" size="small" :aria-label="$t('shell.theme')" data-testid="theme-switch">
    <el-radio-button value="auto">{{ $t('shell.themeAuto') }}</el-radio-button>
    <el-radio-button value="light">{{ $t('shell.themeLight') }}</el-radio-button>
    <el-radio-button value="dark">{{ $t('shell.themeDark') }}</el-radio-button>
  </el-radio-group>
</template>
