<script setup lang="ts">
/** 跨厂商接口映射表：A 侧接口 → B 侧接口；可编辑、CSV 导入导出。两边有接口列表时用下拉，没有（粘贴模式）时用输入框。 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { saveText, toCsv } from '@/views/profiles/csv'
import { initialRows, mapCsvRows, mergePairs, parseMapCsv, setRow, type MapRow } from './ifmap'

const props = defineProps<{
  rows: MapRow[]
  aIfs: string[]
  bIfs: string[]
  aLabel: string
  bLabel: string
  loading: boolean
}>()
const emit = defineEmits<{ (e: 'update:rows', v: MapRow[]): void }>()
const { t } = useI18n()

const open = ref(true)
const msg = ref('')
const fileIn = ref<HTMLInputElement>()
const counts = computed(() => {
  const c = { same: 0, manual: 0, none: 0 }
  for (const r of props.rows) c[r.how]++
  return c
})
const bSorted = computed(() => [...props.bIfs].sort((p, q) => p.localeCompare(q, undefined, { numeric: true })))

function pick(a: string, b: string): void {
  emit('update:rows', setRow(props.rows, a, b))
}
function editA(i: number, a: string): void {
  const rows = props.rows.slice()
  rows[i] = { ...rows[i], a }
  emit('update:rows', setRow(rows, a, rows[i].b))
}
function addRow(): void {
  emit('update:rows', [...props.rows, { a: '', b: '', how: 'none' }])
}
function removeRow(i: number): void {
  emit('update:rows', props.rows.filter((_, k) => k !== i))
}
function reset(): void {
  emit('update:rows', initialRows(props.aIfs, props.bIfs))
  msg.value = ''
}
async function onFile(ev: Event): Promise<void> {
  const input = ev.target as HTMLInputElement
  const f = input.files?.[0]
  input.value = ''
  if (!f) return
  const r = parseMapCsv(await f.text())
  emit('update:rows', mergePairs(props.rows, r.pairs))
  msg.value = t('compare.map.imported', { n: r.pairs.length }) + (r.bad.length ? ' ' + t('compare.map.badLines', { lines: r.bad.join(', ') }) : '')
}
function exportCsv(): void {
  saveText('interface-map.csv', toCsv(mapCsvRows(props.rows)))
}
</script>

<template>
  <div class="map" data-testid="ifmap">
    <div class="map-h">
      <h3><Icon name="map" small />{{ $t('compare.map.title') }}</h3>
      <span class="small muted">{{ $t('compare.map.sub') }}</span>
      <span class="ml-auto row small wrap">
        <span class="tag t-teal">{{ $t('compare.map.same') }} {{ counts.same }}</span>
        <span class="tag t-blue">{{ $t('compare.map.manual') }} {{ counts.manual }}</span>
        <span class="tag">{{ $t('compare.map.none') }} {{ counts.none }}</span>
        <button v-if="aIfs.length" class="btn btn-sm" data-testid="ifmap-reset" @click="reset"><Icon name="refresh" small />{{ $t('compare.map.reset') }}</button>
        <button class="btn btn-sm" data-testid="ifmap-import" @click="fileIn?.click()"><Icon name="upload" small />{{ $t('compare.map.import') }}</button>
        <button class="btn btn-sm" :disabled="!rows.length" data-testid="ifmap-export" @click="exportCsv"><Icon name="download" small />{{ $t('compare.map.export') }}</button>
        <button class="btn btn-ghost btn-sm btn-icon" :title="open ? $t('c.collapse') : $t('c.expand')" :aria-label="open ? $t('c.collapse') : $t('c.expand')" @click="open = !open"><Icon :name="open ? 'chevD' : 'chevR'" small /></button>
      </span>
      <input ref="fileIn" type="file" accept=".csv,.txt,text/csv,text/plain" hidden @change="onFile">
    </div>
    <div v-if="msg" class="map-msg small">{{ msg }}</div>
    <template v-if="open">
      <div v-if="loading" class="empty small">{{ $t('compare.map.loading') }}</div>
      <div v-else class="tbl-wrap map-scroll">
        <table class="tbl compact" data-testid="ifmap-table">
          <thead><tr><th>A · {{ aLabel }}</th><th /><th>B · {{ bLabel }}</th><th>{{ $t('compare.map.how') }}</th><th v-if="!aIfs.length" /></tr></thead>
          <tbody>
            <tr v-for="(r, i) in rows" :key="i" :class="{ unmapped: r.how === 'none' }">
              <td class="mono">
                <template v-if="aIfs.length && aIfs.includes(r.a)">{{ r.a }}</template>
                <input v-else class="input mono cell" :value="r.a" :placeholder="$t('compare.map.aPh')" @change="editA(i, ($event.target as HTMLInputElement).value.trim())">
              </td>
              <td class="arrow">⇄</td>
              <td>
                <select v-if="bIfs.length" class="select cell" :value="r.b" @change="pick(r.a, ($event.target as HTMLSelectElement).value)">
                  <option value="">{{ $t('compare.map.noMap') }}</option>
                  <option v-if="r.b && !bIfs.includes(r.b)" :value="r.b">{{ r.b }}</option>
                  <option v-for="x in bSorted" :key="x" :value="x">{{ x }}</option>
                </select>
                <input v-else class="input mono cell" :value="r.b" :placeholder="$t('compare.map.bPh')" @change="pick(r.a, ($event.target as HTMLInputElement).value.trim())">
              </td>
              <td>
                <span v-if="r.how === 'same'" class="tag t-teal">{{ $t('compare.map.same') }}</span>
                <span v-else-if="r.how === 'manual'" class="tag t-blue">{{ $t('compare.map.manual') }}</span>
                <span v-else class="tag">{{ $t('compare.map.none') }}</span>
              </td>
              <td v-if="!aIfs.length"><button class="btn btn-ghost btn-xs btn-icon" :title="$t('compare.map.remove')" :aria-label="$t('compare.map.remove')" @click="removeRow(i)"><Icon name="x" small /></button></td>
            </tr>
            <tr v-if="!rows.length"><td colspan="5" class="faint small">{{ $t('compare.map.empty') }}</td></tr>
          </tbody>
        </table>
        <div v-if="!aIfs.length" class="map-foot"><button class="btn btn-sm" data-testid="ifmap-add" @click="addRow"><Icon name="plus" small />{{ $t('compare.map.add') }}</button></div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.map { border: 1px solid var(--blue-line); border-radius: 6px; background: color-mix(in srgb, var(--blue-soft) 35%, var(--surface)); }
.map-h { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-bottom: 1px solid var(--blue-line); flex-wrap: wrap; }
.map-h h3 { display: inline-flex; align-items: center; gap: 7px; }
.map-h :deep(.ico) { color: var(--blue-ink); }
.map-h .wrap { flex-wrap: wrap; }
.map-msg { padding: 6px 12px; color: var(--ink-2); border-bottom: 1px solid var(--line); }
.map-scroll { max-height: 320px; overflow: auto; }
.map .tbl th { background: transparent; }
.map .tbl td { background: var(--surface); }
.map .tbl tr.unmapped td { background: transparent; color: var(--ink-3); }
.map .arrow { color: var(--ink-3); text-align: center; width: 30px; }
.cell { height: 26px; font-family: var(--font-mono); font-size: 12px; width: 240px; max-width: 100%; }
.map-foot { padding: 8px 12px; }
</style>
