<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '@/components/Icon.vue'
import { LOGO_SVG } from '@/components/icons'
import { LANGS } from '@/i18n'
import { usePrefs, type Theme } from '@/stores/prefs'
import { useStatus } from '@/stores/status'

const prefs = usePrefs()
const status = useStatus()
const route = useRoute()

interface Item { name: string; icon: string; count?: () => number | undefined; tone?: string }
const NAV: { g: string; s: string; items: Item[] }[] = [
  { g: 'home', s: 'home', items: [{ name: 'dashboard', icon: 'home' }] },
  {
    g: 'dev', s: 'dev', items: [
      { name: 'devices', icon: 'server' },
      { name: 'device-graph', icon: 'graph' },
      { name: 'compare', icon: 'compare' },
      { name: 'check', icon: 'shield' },
      { name: 'unknown-lines', icon: 'unknown', count: () => status.summary?.unknown.patterns, tone: 'plain' },
    ],
  },
  {
    g: 'kb', s: 'kb', items: [
      { name: 'schema-view', icon: 'layers' },
      { name: 'schema-edit', icon: 'tree' },
      { name: 'profiles', icon: 'sliders' },
      { name: 'coverage', icon: 'matrix' },
      { name: 'review', icon: 'inbox', count: () => status.summary?.review.pending, tone: 'amber' },
      { name: 'ingest', icon: 'book' },
      { name: 'releases', icon: 'tag' },
    ],
  },
  { g: 'sys', s: 'sys', items: [{ name: 'ai-settings', icon: 'spark' }] },
]
const THEMES: { v: Theme; icon: string }[] = [
  { v: 'auto', icon: 'monitor' },
  { v: 'light', icon: 'sun' },
  { v: 'dark', icon: 'moon' },
]
const kb = computed(() => status.summary?.kb)

onMounted(() => status.refresh())
watch(() => route.name, () => status.refresh())
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <router-link class="brand" to="/">
        <!-- eslint-disable-next-line vue/no-v-html -->
        <span v-html="LOGO_SVG" style="display: contents" />
        <span class="brand-name">{{ $t('app.name') }}</span>
      </router-link>
      <router-link v-if="kb" class="kbchip" to="/releases" :title="$t('kb.chipTitle')" data-testid="kb-chip">
        <span v-if="kb.draft_changes" class="dot" />
        KB <b>{{ kb.version }}</b>
        <span>{{ kb.draft_changes ? $t('kb.draftChanges', { n: kb.draft_changes }) : $t('kb.noDraft') }}</span>
      </router-link>
      <span class="top-spacer" />
      <div class="top-tools">
        <select v-model="prefs.lang" class="lang-select" aria-label="Language" data-testid="lang-switch">
          <option v-for="l in LANGS" :key="l.code" :value="l.code">{{ l.label }}</option>
        </select>
        <div class="seg" role="group" :aria-label="$t('shell.theme')" data-testid="theme-switch">
          <button v-for="t in THEMES" :key="t.v" type="button" :aria-pressed="prefs.theme === t.v" @click="prefs.theme = t.v">
            <Icon :name="t.icon" small /><span>{{ $t(`theme.${t.v}`) }}</span>
          </button>
        </div>
      </div>
    </header>
    <nav class="nav" aria-label="Main">
      <div v-for="g in NAV" :key="g.g" class="nav-group">
        <div class="nav-gh"><i :class="['stratum', `s-${g.s}`]" /><span>{{ $t(`grp.${g.g}`) }}</span></div>
        <router-link
          v-for="it in g.items"
          :key="it.name"
          :to="{ name: it.name }"
          :data-stratum="g.s"
          :title="$t(`nav.${it.name}`)"
          :aria-current="route.name === it.name || (it.name === 'check' && route.name === 'cleanup') ? 'page' : undefined"
          :data-testid="`nav-${it.name}`"
        >
          <Icon :name="it.icon" />
          <span class="lbl">{{ $t(`nav.${it.name}`) }}</span>
          <span v-if="it.count && it.count()" :class="['count', it.tone]">{{ it.count() }}</span>
        </router-link>
      </div>
      <div class="nav-foot">
        <div :class="status.summary?.ai.configured ? 'ai-on' : 'ai-off'"><i /><span>{{ status.summary?.ai.configured ? $t('foot.aiOn') : $t('foot.ai') }}</span></div>
        <div v-if="status.appVersion">{{ $t('foot.version', { v: status.appVersion }) }}</div>
      </div>
    </nav>
    <slot />
  </div>
</template>
