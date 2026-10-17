<script setup lang="ts">
import LangSwitch from './LangSwitch.vue'
import ThemeSwitch from './ThemeSwitch.vue'
</script>

<template>
  <div class="shell">
    <header class="top">
      <router-link to="/" class="brand">
        <img src="/favicon.svg" alt="" width="28" height="28" />
        <span>{{ $t('app.name') }}</span>
      </router-link>
      <div class="spacer" />
      <LangSwitch />
      <ThemeSwitch />
    </header>
    <main class="main"><slot /></main>
  </div>
</template>

<style scoped>
.shell { display: flex; flex-direction: column; height: 100%; }
.top { display: flex; align-items: center; gap: 12px; padding: 8px 16px; background: var(--lm-surface); border-bottom: 1px solid var(--lm-border); }
.brand { display: flex; align-items: center; gap: 8px; font-weight: 600; color: var(--lm-text); text-decoration: none; }
.spacer { flex: 1; }
.main { flex: 1; overflow: auto; padding: 20px; }
</style>
