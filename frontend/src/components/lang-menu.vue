<script setup lang="ts">
// 顶栏语言按钮（REQ-047，M9-7 预览）：地球图标 + 当前语言简称，点开后列出三种语言（各用本语言书写）。
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { LANGS, type Lang } from '@/i18n'
import { usePrefs } from '@/stores/prefs'

const prefs = usePrefs()
const open = ref(false)
const root = ref<HTMLElement | null>(null)
const SHORT: Record<Lang, string> = { 'zh-CN': '中文', en: 'EN', 'pt-BR': 'PT' }
const short = computed(() => SHORT[prefs.lang] ?? prefs.lang)

async function toggle(): Promise<void> {
  open.value = !open.value
  if (open.value) {
    await nextTick()
    root.value?.querySelector<HTMLElement>('[aria-checked="true"]')?.focus()
  }
}
function choose(code: Lang): void {
  prefs.lang = code
  open.value = false
  root.value?.querySelector<HTMLElement>('.lang-btn')?.focus()
}
function onKey(e: KeyboardEvent): void {
  if (!open.value) return
  if (e.key === 'Escape') { open.value = false; root.value?.querySelector<HTMLElement>('.lang-btn')?.focus(); return }
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
  e.preventDefault()
  const items = Array.from(root.value?.querySelectorAll<HTMLElement>('[role="menuitemradio"]') ?? [])
  const i = items.indexOf(document.activeElement as HTMLElement)
  items[(i + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length]?.focus()
}
function onDoc(e: MouseEvent): void {
  if (open.value && !root.value?.contains(e.target as Node)) open.value = false
}
onMounted(() => document.addEventListener('click', onDoc))
onBeforeUnmount(() => document.removeEventListener('click', onDoc))
</script>

<template>
  <div ref="root" class="langmenu" @keydown="onKey">
    <button type="button" class="lang-btn" aria-haspopup="menu" :aria-expanded="open" :title="$t('shell.language')" :aria-label="$t('shell.language')"
      data-testid="lang-switch" @click="toggle">
      <Icon name="globe" small /><span class="lang-code">{{ short }}</span><Icon name="chevD" small class="chev" />
    </button>
    <div v-if="open" class="lang-pop" role="menu" data-testid="lang-menu">
      <button v-for="l in LANGS" :key="l.code" type="button" role="menuitemradio" :aria-checked="prefs.lang === l.code" :lang="l.code"
        :data-testid="`lang-opt-${l.code}`" @click="choose(l.code)">
        <span class="ln">{{ l.label }}</span><span class="lc">{{ l.code }}</span><Icon name="check" small class="lchk" />
      </button>
      <div class="lang-foot">{{ $t(prefs.syncState === 'local' ? 'shell.langLocal' : 'shell.langAccount') }}</div>
    </div>
  </div>
</template>

<style scoped>
.langmenu { position: relative; }
.lang-btn { display: inline-flex; align-items: center; gap: 5px; height: 30px; padding: 0 7px 0 8px; border: 1px solid var(--line); border-radius: var(--r-ctl);
  background: var(--surface); color: var(--ink-2); font: inherit; font-size: 12.5px; cursor: pointer; }
.lang-btn:hover { border-color: var(--line-strong); color: var(--ink); }
.lang-btn:focus-visible { outline: 2px solid var(--focus); outline-offset: 1px; }
.lang-btn[aria-expanded="true"] { border-color: var(--blue); color: var(--blue-ink); background: var(--blue-soft); }
.lang-code { font-weight: 600; min-width: 2ch; text-align: center; color: var(--ink); }
.lang-btn[aria-expanded="true"] .lang-code { color: var(--blue-ink); }
.chev { width: 12px; height: 12px; color: var(--ink-3); }
.lang-pop { position: absolute; right: 0; top: calc(100% + 6px); width: 232px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
  box-shadow: var(--shadow-pop); padding: 5px; z-index: 70; display: flex; flex-direction: column; }
.lang-pop button { display: grid; grid-template-columns: minmax(0, 1fr) auto 16px; gap: 8px; align-items: center; padding: 8px 9px; border: 0; border-radius: 5px;
  background: none; color: var(--ink); font: inherit; font-size: 13.5px; text-align: left; cursor: pointer; }
.lang-pop button:hover, .lang-pop button:focus-visible { background: var(--surface-2); outline: none; }
.lang-pop button[aria-checked="true"] { background: var(--blue-soft); color: var(--blue-ink); font-weight: 600; }
.lc { font: 11px var(--font-mono); color: var(--ink-3); }
.lchk { visibility: hidden; color: var(--blue-ink); }
.lang-pop button[aria-checked="true"] .lchk { visibility: visible; }
.lang-foot { border-top: 1px solid var(--line); margin-top: 4px; padding: 7px 9px 3px; font-size: 11.5px; color: var(--ink-3); }
@media (max-width: 720px) { .lang-code { display: none; } }
</style>
