<script setup lang="ts">
// 无外壳页面（首次运行向导、令牌页）的顶栏：Logo + 语言 + 主题，写法与 AppShell 一致。
import Icon from '@/components/Icon.vue'
import { LOGO_SVG } from '@/components/icons'
import LangMenu from '@/components/lang-menu.vue'
import { usePrefs, type Theme } from '@/stores/prefs'

const prefs = usePrefs()
const THEMES: { v: Theme; icon: string }[] = [
  { v: 'auto', icon: 'monitor' },
  { v: 'light', icon: 'sun' },
  { v: 'dark', icon: 'moon' },
]
</script>

<template>
  <header class="topbar">
    <span class="brand">
      <!-- eslint-disable-next-line vue/no-v-html -->
      <span v-html="LOGO_SVG" style="display: contents" />
      <span class="brand-name">{{ $t('app.name') }}<small v-if="!$t('app.name').includes('LucidMesh')">LucidMesh</small></span>
    </span>
    <span class="top-spacer" />
    <div class="top-tools">
      <LangMenu />
      <div class="seg" role="group" :aria-label="$t('shell.theme')" data-testid="theme-switch">
        <button v-for="t in THEMES" :key="t.v" type="button" :aria-pressed="prefs.theme === t.v" @click="prefs.theme = t.v">
          <Icon :name="t.icon" small /><span>{{ $t(`theme.${t.v}`) }}</span>
        </button>
      </div>
    </div>
  </header>
</template>
