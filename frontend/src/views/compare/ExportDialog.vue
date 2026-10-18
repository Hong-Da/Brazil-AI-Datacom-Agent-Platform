<script setup lang="ts">
/** 导出对比报告：中文 / English × HTML / Markdown，调用 POST /api/v1/reports（与 /compare 相同的请求体）。 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { i18n } from '@/i18n'
import { useTerms } from '@/stores/terms'
import { dispositionName, reportName } from './setup'

const props = defineProps<{ body: Record<string, unknown> | null; aName: string; bName: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const { t, locale } = useI18n()
const terms = useTerms()

type Lang = 'zh-CN' | 'en'
type Fmt = 'html' | 'md'
const busy = ref('')
const err = ref('')
const LANGS: [Lang, string][] = [['zh-CN', '中文'], ['en', 'English']]
const FMTS: [Fmt, string][] = [['html', 'HTML'], ['md', 'Markdown']]
const name = (lang: Lang, fmt: Fmt) => reportName(props.aName, props.bName, lang, fmt)
const previewLang = computed<Lang>(() => (locale.value === 'zh-CN' ? 'zh-CN' : 'en'))

function token(): string {
  try { return localStorage.getItem('lmesh-token') ?? '' } catch { return '' }
}

/** POST 版的下载（api.ts 的 download 只支持 GET）。 */
async function fetchReport(lang: Lang, fmt: Fmt): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch('/api/v1/reports', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept-Language': String(i18n.global.locale.value),
      Authorization: `Bearer ${token()}`,
    },
    body: JSON.stringify({ kind: 'compare', lang, format: fmt, style: terms.style, compare: props.body }),
  })
  if (res.status === 404 || res.status === 405) throw new Error(t('compare.export.unavailable'))
  const type = res.headers.get('Content-Type') ?? ''
  if (!res.ok || type.includes('application/json')) {
    let msg = res.statusText
    try { msg = ((await res.json()) as { message?: string }).message || msg } catch { /* 不是 JSON */ }
    throw new Error(msg)
  }
  return { blob: await res.blob(), filename: dispositionName(res.headers.get('Content-Disposition')) || name(lang, fmt) }
}

async function download(lang: Lang, fmt: Fmt): Promise<void> {
  if (!props.body) return
  busy.value = `${lang}.${fmt}`
  err.value = ''
  try {
    const r = await fetchReport(lang, fmt)
    const url = URL.createObjectURL(r.blob)
    const a = document.createElement('a')
    a.href = url
    a.download = r.filename
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 0)
  } catch (e) {
    err.value = t('compare.export.failed', { m: e instanceof Error ? e.message : String(e) })
  } finally {
    busy.value = ''
  }
}

async function preview(): Promise<void> {
  if (!props.body) return
  const w = window.open('', '_blank')
  busy.value = 'preview'
  err.value = ''
  try {
    const r = await fetchReport(previewLang.value, 'html')
    const url = URL.createObjectURL(new Blob([r.blob], { type: 'text/html;charset=utf-8' }))
    if (w) w.location.href = url
    else window.open(url, '_blank', 'noopener')
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (e) {
    w?.close()
    err.value = t('compare.export.failed', { m: e instanceof Error ? e.message : String(e) })
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div class="modal-back" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="cmpExT" style="width: min(620px, 100%)" data-testid="export-dialog">
      <div class="modal-h">
        <h2 id="cmpExT">{{ $t('compare.export.title') }}</h2>
        <button class="btn btn-ghost btn-icon btn-sm" :title="$t('c.close')" :aria-label="$t('c.close')" @click="emit('close')"><Icon name="x" small /></button>
      </div>
      <div class="modal-b">
        <p class="muted" style="margin-bottom: 12px">{{ $t('compare.export.sub') }}</p>
        <div v-if="!body" class="notice warn"><Icon name="warn" /><div class="grow">{{ $t('compare.export.needRun') }}</div></div>
        <div v-else class="dl-grid">
          <div class="h" /><div v-for="[, l] in LANGS" :key="l" class="h">{{ l }}</div>
          <template v-for="[f, fl] in FMTS" :key="f">
            <div class="rh">{{ fl }}</div>
            <div v-for="[l] in LANGS" :key="l">
              <button class="link-btn dl-link" :disabled="!!busy" :data-testid="`report-${l}-${f}`" @click="download(l, f)">
                <Icon :name="busy === `${l}.${f}` ? 'refresh' : 'download'" small /><span>{{ $t('compare.export.download') }}</span><small>{{ name(l, f) }}</small>
              </button>
            </div>
          </template>
        </div>
        <div v-if="err" class="notice err mt12" data-testid="report-error"><Icon name="err" /><div class="grow">{{ err }}</div></div>
        <p class="small faint mt12">{{ $t('compare.export.note') }}</p>
      </div>
      <div class="modal-f">
        <button class="btn" :disabled="!body || !!busy" data-testid="report-preview" @click="preview"><Icon name="eye" small /><span>{{ $t('compare.export.preview') }}</span></button>
        <button class="btn btn-primary" @click="emit('close')">{{ $t('c.close') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mt12 { margin-top: 12px; }
.dl-link { text-align: left; flex-wrap: wrap; min-width: 0; max-width: 100%; overflow: hidden; }
.dl-link small { display: block; flex-basis: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
</style>
