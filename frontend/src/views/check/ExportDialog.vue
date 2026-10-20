<script setup lang="ts">
/** 导出检查报告：中文 / English × HTML / Markdown，POST /api/v1/reports（kind=check）直接返回文件。 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText } from '@/api'
import { useTerms } from '@/stores/terms'
import { postFile, reportName, saveBlob, target, targetBody, type ReportFormat, type ReportLang } from './report'
import ReportAiSummary from '@/components/ai-kb/ReportAiSummary.vue'

const props = defineProps<{ device: string | null }>()
const emit = defineEmits<{ close: []; toast: [msg: string, err?: boolean] }>()
const { t, locale } = useI18n()
const busy = ref('')
const terms = useTerms()

const LANGS: { code: ReportLang; label: string }[] = [{ code: 'zh-CN', label: '中文' }, { code: 'en', label: 'English' }]
const FORMATS: { code: ReportFormat; label: string }[] = [{ code: 'html', label: 'HTML' }, { code: 'md', label: 'Markdown' }]

const incAi = ref(true)
const aiParams = computed(() => (target.mode === 'device' && target.deviceId != null ? { device_id: target.deviceId } : null))

function body(lang: ReportLang, format: ReportFormat) {
  return { kind: 'check', lang, format, style: terms.style, check: targetBody(), include_ai_summary: incAi.value }
}

async function dl(lang: ReportLang, format: ReportFormat): Promise<void> {
  busy.value = `${lang}.${format}`
  try {
    const { blob, name } = await postFile('/reports', body(lang, format), reportName('check', props.device, lang, format))
    saveBlob(blob, name)
    emit('toast', t('check.downloaded', { f: name }))
  } catch (e) {
    emit('toast', errorText(e), true)
  } finally {
    busy.value = ''
  }
}

/** 预览：按界面语言（中文界面看中文版，其余看英文版）取 HTML，在新窗口打开。 */
async function preview(): Promise<void> {
  const lang: ReportLang = String(locale.value).startsWith('zh') ? 'zh-CN' : 'en'
  const w = window.open('', '_blank')
  busy.value = 'preview'
  try {
    const { blob } = await postFile('/reports', body(lang, 'html'), 'report.html')
    const url = URL.createObjectURL(new Blob([blob], { type: 'text/html' }))
    if (w) w.location.href = url
    else window.open(url, '_blank')
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (e) {
    w?.close()
    emit('toast', errorText(e), true)
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div class="modal-back" data-testid="export-dialog" @click.self="emit('close')">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="ckExTitle" style="width: min(640px, 100%)">
      <div class="modal-h">
        <h2 id="ckExTitle">{{ $t('check.exportTitle') }}</h2>
        <button class="btn btn-sm btn-ghost btn-icon ml-auto" type="button" :aria-label="$t('c.close')" @click="emit('close')"><Icon name="x" small /></button>
      </div>
      <div class="modal-b">
        <p class="muted small" style="margin-bottom: 10px">{{ $t('check.exportNote') }}</p>
        <p v-if="target.mode === 'text'" class="muted small" style="margin-bottom: 10px">{{ $t('check.exportTextNote') }}</p>
        <ReportAiSummary v-model="incAi" kind="check" :params="aiParams" style="margin-bottom: 12px" />
        <div class="dl-grid">
          <div class="h"></div>
          <div v-for="l in LANGS" :key="l.code" class="h">{{ l.label }}</div>
          <div class="rh">{{ $t('check.exportReport') }}</div>
          <div v-for="l in LANGS" :key="l.code" class="dl-cell">
            <button
              v-for="f in FORMATS" :key="f.code" type="button" class="link-btn dl-link" :disabled="!!busy"
              :data-testid="`export-${l.code}-${f.code}`" @click="dl(l.code, f.code)"
            >
              <Icon :name="busy === `${l.code}.${f.code}` ? 'refresh' : 'download'" small />{{ f.label }}
              <small>{{ reportName('check', device, l.code, f.code) }}</small>
            </button>
          </div>
        </div>
      </div>
      <div class="modal-f">
        <button class="btn btn-sm" type="button" :disabled="!!busy" data-testid="export-preview" @click="preview"><Icon name="eye" small />{{ $t('check.exportPreview') }}</button>
        <button class="btn btn-sm btn-primary" type="button" @click="emit('close')">{{ $t('c.close') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dl-grid > div.dl-cell { flex-direction: column; align-items: flex-start; gap: 4px; }
.dl-link { background: none; border: 0; padding: 0; cursor: pointer; color: var(--blue-ink); font: inherit; font-size: 12.5px; text-align: left; flex-wrap: wrap; }
.dl-link:disabled { opacity: .6; cursor: default; }
.dl-link small { word-break: break-all; }
</style>
