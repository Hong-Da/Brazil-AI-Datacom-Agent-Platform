<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { errorText, post } from '@/api'
import {
  acceptFile, fmtBytes, importTotals, MAX_FILE_BYTES, sanitizedEntries, sanitizedTotal, vendorLabel,
  type ImportFileResult,
} from './logic'

const emit = defineEmits<{ close: []; imported: [results: ImportFileResult[]] }>()

type Src = 'file' | 'folder' | 'zip'
const step = ref(0) // 0 选择文件，1 脱敏级别，2 导入结果
const src = ref<Src>('file')
const level = ref<'basic' | 'strict'>('basic')
const files = ref<File[]>([])
const skipped = ref<{ name: string; why: 'type' | 'size' }[]>([])
const uploading = ref(false)
const error = ref('')
const results = ref<ImportFileResult[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const dragging = ref(false)

const totalBytes = computed(() => files.value.reduce((a, f) => a + f.size, 0))
const totals = computed(() => importTotals(results.value))
const STEPS = ['stepSource', 'stepLevel', 'stepResult'] as const

function relName(f: File): string {
  return f.webkitRelativePath || f.name
}
function addFiles(list: FileList | File[]): void {
  const keep = [...files.value]
  const skip = [...skipped.value]
  for (const f of Array.from(list)) {
    const name = relName(f)
    if (!acceptFile(f.name)) { if (src.value !== 'folder') skip.push({ name, why: 'type' }); continue }
    if (f.size > MAX_FILE_BYTES) { skip.push({ name, why: 'size' }); continue }
    if (!keep.some((k) => k.name === f.name && k.size === f.size && k.lastModified === f.lastModified)) keep.push(f)
  }
  files.value = keep
  skipped.value = skip
}
function onPick(e: Event): void {
  const input = e.target as HTMLInputElement
  if (input.files) addFiles(input.files)
  input.value = ''
}
function onDrop(e: DragEvent): void {
  dragging.value = false
  if (e.dataTransfer?.files) addFiles(e.dataTransfer.files)
}
function browse(): void {
  const el = fileInput.value
  if (!el) return
  el.webkitdirectory = src.value === 'folder'
  el.multiple = src.value !== 'zip'
  el.accept = src.value === 'zip' ? '.zip' : src.value === 'file' ? '.cfg,.txt,.log,.conf,.config' : ''
  el.click()
}
function removeFile(i: number): void {
  files.value = files.value.filter((_, j) => j !== i)
}
function clearFiles(): void {
  files.value = []
  skipped.value = []
}

async function upload(): Promise<void> {
  step.value = 2
  uploading.value = true
  error.value = ''
  results.value = []
  try {
    const fd = new FormData()
    for (const f of files.value) fd.append('files', f, f.name)
    fd.append('level', level.value)
    const data = await post<{ files: ImportFileResult[] }>('/configs', fd)
    results.value = data.files
    emit('imported', data.files)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    uploading.value = false
  }
}

function close(): void {
  if (!uploading.value) emit('close')
}
function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') close()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="modal-back" @click.self="close">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="imp-title" data-testid="import-dialog">
      <div class="modal-h">
        <h2 id="imp-title">{{ $t('devices.import') }}</h2>
        <button class="btn btn-ghost btn-icon" :aria-label="$t('c.close')" :disabled="uploading" @click="close"><Icon name="x" /></button>
      </div>
      <div class="steps">
        <div v-for="(s, i) in STEPS" :key="s" class="st" :class="{ done: i < step, cur: i === step }">
          <span class="no"><Icon v-if="i < step" name="check" small /><template v-else>{{ i + 1 }}</template></span>
          <span>{{ $t('devices.' + s) }}</span>
        </div>
      </div>

      <div class="modal-b">
        <!-- 1. 选择文件 -->
        <template v-if="step === 0">
          <div class="radio-cards src-cards" data-testid="import-source">
            <label class="radio-card"><input v-model="src" type="radio" value="file"><span><Icon name="file" /></span><span><span class="rc-t">{{ $t('devices.srcFile') }}</span><br><span class="rc-d">{{ $t('devices.srcFileD') }}</span></span></label>
            <label class="radio-card"><input v-model="src" type="radio" value="folder"><span><Icon name="folder" /></span><span><span class="rc-t">{{ $t('devices.srcFolder') }}</span><br><span class="rc-d">{{ $t('devices.srcFolderD') }}</span></span></label>
            <label class="radio-card"><input v-model="src" type="radio" value="zip"><span><Icon name="zip" /></span><span><span class="rc-t">{{ $t('devices.srcZip') }}</span><br><span class="rc-d">{{ $t('devices.srcZipD') }}</span></span></label>
          </div>
          <div
            class="dropzone mt12" :class="{ over: dragging }" data-testid="dropzone"
            @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="onDrop"
          >
            <Icon name="upload" />
            <div>{{ $t('devices.dropHint') }} <button class="link-btn" type="button" data-testid="browse" @click="browse">{{ $t('devices.browse') }}</button></div>
            <div class="small faint mt8">{{ $t('devices.dropLimit') }}</div>
            <input ref="fileInput" type="file" hidden data-testid="file-input" @change="onPick">
          </div>
          <div v-if="skipped.length" class="notice warn mt12">
            <Icon name="warn" />
            <div class="grow small">
              {{ $t('devices.skippedN', { n: skipped.length }) }}
              <span v-for="s in skipped.slice(0, 5)" :key="s.name" class="skip"><span class="mono">{{ s.name }}</span> · {{ $t(s.why === 'size' ? 'devices.tooBig' : 'devices.notConfig') }}</span>
            </div>
          </div>
          <div v-if="files.length" class="chosen">
            <div class="section-t">{{ $t('devices.chosen') }}<button class="link-btn" type="button" style="font-weight: 400" @click="clearFiles">{{ $t('devices.clear') }}</button></div>
            <div class="tbl-wrap" style="max-height: 220px">
              <table class="tbl compact" data-testid="chosen-files">
                <tbody>
                  <tr v-for="(f, i) in files" :key="f.name + f.size + i">
                    <td style="width: 24px"><Icon :name="f.name.toLowerCase().endsWith('.zip') ? 'zip' : 'file'" small /></td>
                    <td class="mono">{{ relName(f) }}</td>
                    <td class="faint right">{{ fmtBytes(f.size) }}</td>
                    <td style="width: 30px"><button class="btn btn-ghost btn-icon btn-xs" :aria-label="$t('c.delete')" @click="removeFile(i)"><Icon name="x" small /></button></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>

        <!-- 2. 脱敏级别 -->
        <template v-else-if="step === 1">
          <div class="radio-cards" data-testid="sanitize-level">
            <label class="radio-card"><input v-model="level" type="radio" value="basic"><span><Icon name="shield" /></span><span><span class="rc-t">basic · {{ $t('devices.lvBasic') }}</span><br><span class="rc-d">{{ $t('devices.lvBasicD') }}</span></span></label>
            <label class="radio-card"><input v-model="level" type="radio" value="strict"><span><Icon name="lock" /></span><span><span class="rc-t">strict · {{ $t('devices.lvStrict') }}</span><br><span class="rc-d">{{ $t('devices.lvStrictD') }}</span></span></label>
          </div>
          <div class="notice ok mt12"><Icon name="sanitize" /><div class="grow small">{{ $t('devices.sanitizeNote') }}</div></div>
          <p class="small muted mt12">{{ $t('devices.levelFlow') }}</p>
        </template>

        <!-- 3. 导入结果 -->
        <template v-else>
          <div v-if="uploading" class="stack" data-testid="import-progress">
            <div class="row"><b>{{ $t('devices.uploading', { n: files.length }) }}</b><span class="faint small ml-auto">{{ fmtBytes(totalBytes) }}</span></div>
            <div class="progress striped"><i style="width: 100%" /></div>
            <p class="small muted">{{ $t('devices.uploadingNote') }}</p>
          </div>
          <div v-else-if="error" class="notice err" data-testid="import-error">
            <Icon name="err" /><div class="grow">{{ error }}</div>
            <button class="btn btn-sm" @click="upload">{{ $t('c.retry') }}</button>
          </div>
          <template v-else>
            <div class="notice" :class="totals.failed ? 'warn' : 'ok'">
              <Icon :name="totals.failed ? 'warn' : 'ok'" />
              <div class="grow">{{ $t('devices.resultSummary', { n: totals.files, ok: totals.ok, f: totals.failed, r: totals.replacements, u: totals.unknown }) }}</div>
            </div>
            <div class="tbl-wrap mt12" style="max-height: 420px">
              <table class="tbl" data-testid="import-results">
                <thead>
                  <tr>
                    <th>{{ $t('devices.colFile') }}</th>
                    <th>{{ $t('devices.colDetected') }}</th>
                    <th>Profile</th>
                    <th class="num">{{ $t('devices.colLines') }}</th>
                    <th class="num">{{ $t('devices.colUnknown') }}</th>
                    <th>{{ $t('devices.colSanitized') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(r, i) in results" :key="r.source + i" :class="{ failed: !r.ok }">
                    <td class="mono nowrap">
                      {{ r.source }}
                      <div v-if="r.ok" class="small faint" style="font-family: var(--font-ui)">{{ $t('devices.deviceName') }} <span class="mono">{{ r.device }}</span></div>
                    </td>
                    <td v-if="!r.ok" colspan="5"><span class="tag fail">{{ $t('c.failed') }}</span> <span class="small">{{ r.error }}</span></td>
                    <template v-else>
                      <td class="nowrap">
                        <span v-if="r.vendor" class="vendor"><i :class="r.vendor === 'huawei' ? 'hw' : r.vendor === 'cisco' ? 'cs' : ''">{{ r.vendor === 'huawei' ? 'HW' : r.vendor === 'cisco' ? 'CS' : '?' }}</i>{{ vendorLabel(r.vendor) }}</span>
                        <span v-else class="tag warn">{{ $t('devices.vendorUnknown') }}</span>
                        <div class="mono faint small">{{ r.version || $t('devices.noVersion') }}</div>
                      </td>
                      <td class="mono nowrap">{{ r.profile || '—' }}</td>
                      <td class="num">{{ r.lines.toLocaleString() }}</td>
                      <td class="num" :class="r.unknown ? 'unk' : 'faint'">{{ r.unknown }}</td>
                      <td>
                        <span v-if="!sanitizedTotal(r.sanitized)" class="faint small">{{ $t('devices.noReplacements') }}</span>
                        <span v-for="[k, n] in sanitizedEntries(r.sanitized)" :key="k" class="tag san">{{ $t('devices.cat.' + k) }} {{ n }}</span>
                      </td>
                    </template>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
        </template>
      </div>

      <div class="modal-f">
        <template v-if="step === 0">
          <span class="faint small" style="margin-right: auto">{{ files.length ? $t('devices.filesSize', { n: files.length, s: fmtBytes(totalBytes) }) : $t('devices.noFiles') }}</span>
          <button class="btn" @click="close">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" :disabled="!files.length" data-testid="to-level" @click="step = 1">{{ $t('devices.toLevel') }}</button>
        </template>
        <template v-else-if="step === 1">
          <button class="btn" @click="step = 0">{{ $t('c.back') }}</button>
          <button class="btn btn-primary" data-testid="start-import" @click="upload"><Icon name="upload" small />{{ $t('devices.startImport') }}</button>
        </template>
        <template v-else>
          <button v-if="!uploading && error" class="btn" @click="step = 1">{{ $t('c.back') }}</button>
          <button v-if="!uploading && !error" class="btn" @click="clearFiles(); results = []; step = 0">{{ $t('devices.importMore') }}</button>
          <button class="btn btn-primary" :disabled="uploading" data-testid="import-done" @click="close">{{ $t('c.close') }}</button>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal { width: min(1080px, 100%); }
.steps { padding: 12px 18px; border-bottom: 1px solid var(--line); background: var(--surface-2); }
.modal-b { min-height: 380px; }
.src-cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.dropzone.over { border-color: var(--teal); background: var(--teal-soft); }
.chosen { margin-top: 14px; }
.chosen .tbl td { padding: 5px 10px; }
.tbl td.nowrap { white-space: nowrap; }
.tbl .unk { color: var(--red-ink); font-weight: 600; }
tr.failed td { background: color-mix(in srgb, var(--red-soft) 55%, transparent); }
.tag.san { margin: 0 4px 2px 0; }
.skip { margin-left: 10px; }
@media (max-width: 1100px) { .src-cards { grid-template-columns: 1fr; } }
</style>
