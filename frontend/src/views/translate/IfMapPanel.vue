<script setup lang="ts">
/**
 * 接口映射表（源接口 → 目标接口）：没填的接口保持原名；子接口由后端按父接口映射。CSV 导入导出。
 * 目标设备的端口清单后端没有提供，目标接口用输入框填写。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { saveText, toCsv } from '@/views/profiles/csv'
import { mapCsvRows, mergePairs, parseMapCsv, setRow, type MapRow } from '@/views/compare/ifmap'

const props = defineProps<{ rows: MapRow[]; loading: boolean; dirty: boolean }>()
const emit = defineEmits<{ (e: 'update:rows', v: MapRow[]): void; (e: 'reset'): void }>()
const { t } = useI18n()
const open = ref(true)
const msg = ref('')
const fileIn = ref<HTMLInputElement>()
const manual = computed(() => props.rows.filter((r) => r.how === 'manual').length)

function pick(a: string, b: string): void {
  emit('update:rows', setRow(props.rows, a, b))
}
async function onFile(ev: Event): Promise<void> {
  const input = ev.target as HTMLInputElement
  const f = input.files?.[0]
  input.value = ''
  if (!f) return
  const r = parseMapCsv(await f.text())
  emit('update:rows', mergePairs(props.rows, r.pairs))
  msg.value = t('translate.map.imported', { n: r.pairs.length }) + (r.bad.length ? ' ' + t('translate.map.badLines', { lines: r.bad.join(', ') }) : '')
}
function exportCsv(): void {
  saveText('interface-map.csv', toCsv(mapCsvRows(props.rows)))
}
</script>

<template>
  <div class="map" :class="{ open }" data-testid="tr-ifmap">
    <div class="map-h" role="button" tabindex="0" :aria-expanded="open" @click.self="open = !open" @keydown.enter.self="open = !open">
      <span class="twk" @click="open = !open"><Icon :name="open ? 'chevD' : 'chevR'" small /></span>
      <h3 @click="open = !open"><Icon name="map" small />{{ $t('translate.map.title') }}</h3>
      <span class="meta" @click="open = !open">{{ loading ? $t('c.loading') : $t('translate.map.meta', { n: rows.length, m: manual }) }}</span>
      <span v-if="dirty" class="tag t-amber">{{ $t('translate.map.dirty') }}</span>
      <span class="ml-auto row" style="gap: 6px">
        <button class="btn btn-sm" type="button" :disabled="!rows.length" @click="emit('reset')"><Icon name="refresh" small />{{ $t('translate.map.reset') }}</button>
        <button class="btn btn-sm" type="button" data-testid="tr-ifmap-import" @click="fileIn?.click()"><Icon name="upload" small />{{ $t('translate.map.import') }}</button>
        <button class="btn btn-sm" type="button" :disabled="!rows.length" @click="exportCsv"><Icon name="download" small />{{ $t('translate.map.export') }}</button>
      </span>
      <input ref="fileIn" type="file" accept=".csv,.txt,text/csv,text/plain" hidden @change="onFile">
    </div>
    <div v-if="msg && open" class="map-msg small">{{ msg }}</div>
    <template v-if="open">
      <div class="tbl-wrap map-scroll">
        <table class="tbl compact">
          <thead><tr><th>{{ $t('translate.map.src') }}</th><th /><th>{{ $t('translate.map.dst') }}</th><th>{{ $t('translate.map.how') }}</th></tr></thead>
          <tbody>
            <tr v-for="r in rows" :key="r.a">
              <td class="mono">{{ r.a }}</td>
              <td class="arrowc">→</td>
              <td><input class="input mono cell" :value="r.b" :placeholder="r.a" :aria-label="r.a" @change="pick(r.a, ($event.target as HTMLInputElement).value.trim())"></td>
              <td>
                <span v-if="r.how === 'manual'" class="how manual">{{ $t('translate.map.manual') }}</span>
                <span v-else class="how keep">{{ $t('translate.map.keep') }}</span>
              </td>
            </tr>
            <tr v-if="!rows.length"><td colspan="4" class="faint small">{{ loading ? $t('c.loading') : $t('translate.map.empty') }}</td></tr>
          </tbody>
        </table>
      </div>
      <div class="map-f"><Icon name="info" small /><span>{{ $t('translate.map.foot') }}</span></div>
    </template>
  </div>
</template>

<style scoped>
.map { border: 1px solid var(--blue-line); border-radius: 6px; background: color-mix(in srgb, var(--blue-soft) 35%, var(--surface)); }
.map-h { display: flex; align-items: center; gap: 10px; padding: 8px 12px; flex-wrap: wrap; cursor: pointer; user-select: none; }
.map.open .map-h { border-bottom: 1px solid var(--blue-line); }
.map-h h3 { display: inline-flex; align-items: center; gap: 7px; }
.map-h :deep(.ico) { color: var(--blue-ink); }
.map-h .meta { color: var(--ink-2); font-size: 12px; }
.map-msg { padding: 6px 12px; color: var(--ink-2); border-bottom: 1px solid var(--line); }
.map-scroll { max-height: 300px; overflow: auto; }
.map .tbl th { background: transparent; }
.map .tbl td { background: var(--surface); }
.arrowc { color: var(--ink-3); text-align: center; width: 28px; }
.cell { height: 26px; font-family: var(--font-mono); font-size: 12px; width: 260px; max-width: 100%; }
.map-f { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-top: 1px solid var(--blue-line); font-size: 12px; color: var(--ink-2); flex-wrap: wrap; }
.how { font-size: 12px; }
.how.manual { color: var(--blue-ink); }
.how.keep { color: var(--ink-2); }
</style>
