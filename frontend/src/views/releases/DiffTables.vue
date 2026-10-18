<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { diffCounts, fmtValue, type KbDiff } from './logic'

const props = defineProps<{ diff: KbDiff }>()
const CAP = 100
const showAllCards = ref(false)

const c = computed(() => diffCounts(props.diff))
const nodeRows = computed(() => [
  ...props.diff.nodes_added.map((id) => ({ id, k: 'added', tone: 't-teal' })),
  ...props.diff.nodes_semantic.map((id) => ({ id, k: 'semantic', tone: 't-blue' })),
  ...props.diff.nodes_removed.map((id) => ({ id, k: 'removed', tone: 't-red' })),
  ...props.diff.nodes_deprecated.map((id) => ({ id, k: 'deprecated', tone: 'deprecated' })),
])
const cardRows = computed(() => [
  ...props.diff.cards_added.map((id) => ({ id, k: 'added', tone: 't-teal' })),
  ...props.diff.cards_changed.map((id) => ({ id, k: 'changed', tone: 't-blue' })),
  ...props.diff.cards_removed.map((id) => ({ id, k: 'removed', tone: 't-red' })),
])
const cardShown = computed(() => (showAllCards.value ? cardRows.value : cardRows.value.slice(0, CAP)))
</script>

<template>
  <div data-testid="diff-tables">
    <div class="legend" style="margin-bottom: 12px">
      <span><i style="background: var(--teal)" />{{ $t('releases.lgAdded', { n: c.nodes_added }) }}</span>
      <span><i style="background: var(--blue)" />{{ $t('releases.lgSemantic', { n: c.nodes_semantic }) }}</span>
      <span><i style="background: var(--red)" />{{ $t('releases.lgRemoved', { n: c.nodes_removed }) }}</span>
      <span><i style="background: var(--ink-3)" />{{ $t('releases.lgDeprecated', { n: c.nodes_deprecated }) }}</span>
      <span><i style="background: var(--amber)" />{{ $t('releases.lgDefaults', { n: c.defaults_changed }) }}</span>
      <span>{{ $t('releases.lgCards', { a: c.cards_added, m: c.cards_changed, r: c.cards_removed }) }}</span>
      <span class="bump-sug">{{ $t('releases.suggestedBump') }} <b :class="['bump', diff.suggested_bump]">{{ diff.suggested_bump }}</b></span>
    </div>
    <div v-if="!c.total" class="empty"><p>{{ $t('releases.noDiff') }}</p></div>
    <div v-else class="grid g2">
      <div>
        <h3>{{ $t('releases.nodeChanges') }}</h3>
        <table v-if="nodeRows.length" class="tbl mt8">
          <thead><tr><th>{{ $t('releases.change') }}</th><th>{{ $t('releases.node') }}</th></tr></thead>
          <tbody><tr v-for="r in nodeRows" :key="r.k + r.id"><td><span :class="['tag', r.tone]">{{ $t(`releases.ch_${r.k}`) }}</span></td><td class="mono">{{ r.id }}</td></tr></tbody>
        </table>
        <p v-else class="small faint mt8">{{ $t('c.none') }}</p>

        <template v-if="diff.profiles_added.length">
          <h3 class="mt16">{{ $t('releases.profilesAdded') }}</h3>
          <div class="row wrap mt8"><span v-for="p in diff.profiles_added" :key="p" class="tag mono">{{ p }}</span></div>
        </template>

        <h3 class="mt16">{{ $t('releases.cardChanges') }}</h3>
        <table v-if="cardRows.length" class="tbl compact mt8">
          <thead><tr><th>{{ $t('releases.change') }}</th><th>{{ $t('releases.card') }}</th></tr></thead>
          <tbody><tr v-for="r in cardShown" :key="r.k + r.id"><td><span :class="['tag', r.tone]">{{ $t(`releases.ch_${r.k}`) }}</span></td><td class="mono small">{{ r.id }}</td></tr></tbody>
        </table>
        <p v-else class="small faint mt8">{{ $t('c.none') }}</p>
        <button v-if="cardRows.length > CAP" class="btn btn-sm btn-ghost mt8" type="button" @click="showAllCards = !showAllCards">
          {{ showAllCards ? $t('c.collapse') : $t('releases.showAll', { n: cardRows.length }) }}
        </button>
      </div>
      <div>
        <h3>{{ $t('releases.defaultChanges') }}</h3>
        <table v-if="diff.defaults_changed.length" class="tbl mt8">
          <thead><tr><th>{{ $t('releases.node') }}</th><th>Profile</th><th>{{ $t('releases.old') }}</th><th>{{ $t('releases.new') }}</th></tr></thead>
          <tbody>
            <tr v-for="d in diff.defaults_changed" :key="d.profile + d.node">
              <td class="mono">{{ d.node }}</td><td class="mono small">{{ d.profile }}</td>
              <td class="mono old">{{ fmtValue(d.old) }}</td><td class="mono">{{ fmtValue(d.new) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="small faint mt8">{{ $t('c.none') }}</p>
        <div class="notice info mt16"><Icon name="info" /><div class="grow small">{{ $t('releases.bumpRule') }}</div></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.old { text-decoration: line-through; color: var(--ink-3); }
.bump { font: 600 11px var(--font-mono); }
.bump.major { color: var(--red-ink); }
.bump.minor { color: var(--teal-ink); }
.bump.patch { color: var(--ink-2); }
.bump-sug { margin-left: auto; }
.tbl td.mono, .tbl td.small.mono { white-space: nowrap; }
</style>
