<script setup lang="ts">
/** AI 查询的会话列表（REQ-052，预览 DevelopDocs/ui-preview/REQ-052/sessions.html）：进行中 / 已归档 / 分享给我，按最近更新分组。 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { dayGroup, shortWhen, type SessionBrief, type SessionWhich } from './ask-sessions'

const props = defineProps<{ sessions: SessionBrief[]; counts: Record<SessionWhich, number>; which: SessionWhich; current: number | null; loading?: boolean; netNames?: Record<string, string> }>()
const emit = defineEmits<{ (e: 'which', w: SessionWhich): void; (e: 'select', id: number): void; (e: 'new'): void; (e: 'search', q: string): void }>()
const { t } = useI18n()
const q = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
watch(q, (v) => { clearTimeout(timer); timer = setTimeout(() => emit('search', v), 250) })

const groups = computed(() => {
  const out: { key: string; label: string; items: SessionBrief[] }[] = []
  for (const s of props.sessions) {
    const g = dayGroup(s.updated_at)
    let last = out[out.length - 1]
    if (!last || last.key !== g) { last = { key: g, label: t(`ask.ses.day.${g}`), items: [] }; out.push(last) }
    last.items.push(s)
  }
  return out
})
const empty = computed(() => t(props.which === 'archived' ? 'ask.ses.noArchived' : props.which === 'shared' ? 'ask.ses.noShared' : 'ask.ses.none'))
</script>

<template>
  <aside class="panel rail" data-testid="ask-rail">
    <div class="rail-h">
      <h3>{{ $t('ask.ses.title') }}</h3>
      <button class="btn btn-sm btn-primary" type="button" data-testid="ask-ses-new" @click="emit('new')"><Icon name="plus" small /><span>{{ $t('ask.ses.new') }}</span></button>
    </div>
    <label class="input-wrap rail-q"><Icon name="search" small /><input v-model="q" class="input" type="search" :placeholder="$t('ask.ses.search')" data-testid="ask-ses-q"></label>
    <div class="seg rail-seg" role="group">
      <button v-for="w in (['active', 'archived', 'shared'] as SessionWhich[])" :key="w" type="button" :aria-pressed="which === w" :data-testid="`ask-ses-tab-${w}`" @click="emit('which', w)">{{ $t(`ask.ses.tab.${w}`) }} {{ counts[w] ?? 0 }}</button>
    </div>
    <ul class="slist" :aria-busy="loading">
      <template v-for="g in groups" :key="g.key">
        <li class="grp">{{ g.label }}</li>
        <li v-for="s in g.items" :key="s.id" class="it" :aria-current="s.id === current" :data-testid="`ask-ses-${s.id}`" tabindex="0" @click="emit('select', s.id)" @keydown.enter="emit('select', s.id)">
          <span class="t">{{ s.title || $t('ask.ses.untitled') }}</span>
          <span class="when">{{ shortWhen(s.updated_at) }}</span>
          <span class="m">
            <template v-if="!s.mine"><Icon name="user" small />{{ s.owner }} · {{ $t('ask.ses.readOnly') }}</template>
            <template v-else>{{ (s.network && netNames?.[s.network]) || s.network || $t('ask.ses.defaultNet') }} · {{ $t('ask.ses.nTurns', { n: s.turns }) }}<template v-if="s.attachments"> · <Icon name="upload" small />{{ s.attachments }}</template><template v-if="s.shared"> · <Icon name="users" small />{{ $t('ask.ses.shared') }}</template></template>
          </span>
        </li>
      </template>
      <li v-if="!sessions.length" class="rail-empty">{{ empty }}</li>
    </ul>
  </aside>
</template>

<style scoped>
.rail { align-self: start; position: sticky; top: 0; max-height: calc(100vh - 140px); display: flex; flex-direction: column; }
.rail-h { display: flex; align-items: center; gap: 8px; padding: 10px 12px 8px; }
.rail-h h3 { margin: 0; font-size: 13.5px; }
.rail-h .btn { margin-left: auto; }
.rail-q { margin: 0 12px 8px; }
.rail-seg { margin: 0 12px 8px; display: flex; }
.rail-seg button { flex: 1; white-space: nowrap; padding-left: 6px; padding-right: 6px; }
.slist { list-style: none; margin: 0; padding: 0 6px 8px; overflow: auto; }
.slist .it { border-radius: 6px; padding: 7px 8px; cursor: pointer; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 6px; }
.slist .it:hover, .slist .it:focus-visible { background: var(--surface-2); outline: none; }
.slist .it[aria-current="true"] { background: var(--blue-soft); }
.slist .t { font-size: 13px; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.slist .when { font-size: 11.5px; color: var(--ink-3); }
.slist .m { grid-column: 1 / -1; font-size: 11.5px; color: var(--ink-3); display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
.slist .grp { font-size: 11px; color: var(--ink-3); padding: 8px 8px 2px; }
.rail-empty { padding: 16px 12px; font-size: 12.5px; color: var(--ink-3); }
</style>
