<script setup lang="ts">
/**
 * AI 查询会话的头部（REQ-052～054）：标题（重命名）、分享 / 归档 / 删除、下载（会话报告 HTML / Markdown 中英文、
 * 打印为 PDF、AI 报告 Markdown）。别人分享的会话只读：只有下载。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { apiUrl, errorText, post } from '@/api'
import type { AiReport, SessionFull } from './ask-sessions'

const props = defineProps<{ session: SessionFull; aiOn: boolean }>()
const emit = defineEmits<{ (e: 'patch', changes: Record<string, unknown>): void; (e: 'delete'): void }>()
const { t, locale } = useI18n()

const renaming = ref(false)
const title = ref('')
const titleIn = ref<HTMLInputElement | null>(null)
async function startRename(): Promise<void> {
  menu.value = false
  title.value = props.session.title
  renaming.value = true
  await nextTick()
  titleIn.value?.focus()
}
function saveTitle(): void {
  const v = title.value.trim()
  renaming.value = false
  if (v && v !== props.session.title) emit('patch', { title: v })
}

const menu = ref(false)
const dl = ref(false)
function close(e: MouseEvent): void {
  const el = e.target as HTMLElement
  if (!el.closest('.sh-menu')) menu.value = false
  if (!el.closest('.sh-dl')) dl.value = false
}
onMounted(() => document.addEventListener('click', close))
onBeforeUnmount(() => document.removeEventListener('click', close))

const base = computed(() => `/ask/sessions/${props.session.id}`)
function reportUrl(lang: 'zh-CN' | 'en', format: 'html' | 'md'): string {
  return apiUrl(`${base.value}/report?lang=${lang}&format=${format}`)
}
const printLang = computed<'zh-CN' | 'en'>(() => (String(locale.value) === 'zh-CN' ? 'zh-CN' : 'en'))
function printPdf(): void {
  dl.value = false
  const w = window.open(reportUrl(printLang.value, 'html'), '_blank')
  if (w) w.addEventListener('load', () => { try { w.print() } catch { /* 用户可以自己按打印 */ } })
}

const rep = ref<AiReport | null>(null)
const repBusy = ref(false)
const repErr = ref('')
const repOpen = ref(false)
async function aiReport(): Promise<void> {
  dl.value = false
  repOpen.value = true
  repBusy.value = true
  repErr.value = ''
  rep.value = null
  try { rep.value = await post<AiReport>(`${base.value}/ai-report`, { lang: String(locale.value) }) } catch (e) { repErr.value = errorText(e) } finally { repBusy.value = false }
}
function saveMd(): void {
  if (!rep.value) return
  const url = URL.createObjectURL(new Blob([rep.value.markdown], { type: 'text/markdown;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = rep.value.filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function confirmDelete(): void {
  menu.value = false
  if (window.confirm(t('ask.ses.deleteConfirm', { title: props.session.title || t('ask.ses.untitled') }))) emit('delete')
}
</script>

<template>
  <div>
    <div v-if="!session.mine" class="ro-banner" data-testid="ask-ses-readonly"><Icon name="eye" small /><span>{{ $t('ask.ses.roBanner', { owner: session.owner }) }}</span></div>
    <div class="sh">
      <template v-if="renaming">
        <input ref="titleIn" v-model="title" class="input title-in" maxlength="200" data-testid="ask-ses-title-in" @keydown.enter="saveTitle" @keydown.esc="renaming = false">
        <button class="btn btn-sm btn-primary" type="button" data-testid="ask-ses-title-ok" @click="saveTitle">{{ $t('c.save') }}</button>
        <button class="btn btn-sm" type="button" @click="renaming = false">{{ $t('c.cancel') }}</button>
      </template>
      <template v-else>
        <span class="title" data-testid="ask-ses-title">{{ session.title || $t('ask.ses.untitled') }}</span>
        <span v-if="session.shared" class="tag shared">{{ $t('ask.ses.sharedTag') }}</span>
        <span v-if="session.archived" class="tag">{{ $t('ask.ses.archivedTag') }}</span>
      </template>
      <span class="acts">
        <span class="rel sh-dl">
          <button class="btn btn-sm" type="button" :aria-expanded="dl" data-testid="ask-ses-dl" @click="dl = !dl"><Icon name="download" small /><span>{{ $t('ask.dl.title') }}</span> ▾</button>
          <div v-if="dl" class="menu-pop" role="menu">
            <div class="h">{{ $t('ask.dl.byCode') }}</div>
            <a :href="reportUrl('zh-CN', 'html')" target="_blank" rel="noopener" data-testid="ask-dl-html-zh" @click="dl = false"><Icon name="report" small />HTML · 中文<span class="k">zh-CN</span></a>
            <a :href="reportUrl('en', 'html')" target="_blank" rel="noopener" data-testid="ask-dl-html-en" @click="dl = false"><Icon name="report" small />HTML · English<span class="k">en</span></a>
            <a :href="reportUrl('zh-CN', 'md')" data-testid="ask-dl-md-zh" @click="dl = false"><Icon name="file" small />Markdown · 中文<span class="k">.md</span></a>
            <a :href="reportUrl('en', 'md')" data-testid="ask-dl-md-en" @click="dl = false"><Icon name="file" small />Markdown · English<span class="k">.md</span></a>
            <button type="button" data-testid="ask-dl-pdf" @click="printPdf"><Icon name="printer" small />{{ $t('ask.dl.pdf') }}<span class="k">{{ $t('ask.dl.pdfHint') }}</span></button>
            <template v-if="aiOn && session.turn_list.length">
              <div class="sep" />
              <div class="h">{{ $t('ask.dl.ai') }}</div>
              <button type="button" data-testid="ask-dl-ai" @click="aiReport"><Icon name="spark" small />{{ $t('ask.dl.aiWrite') }}<span class="k">{{ $t('ask.dl.aiChecked') }}</span></button>
            </template>
          </div>
        </span>
        <span v-if="session.mine" class="rel sh-menu">
          <button class="btn btn-sm btn-icon" type="button" :aria-label="$t('ask.ses.more')" aria-haspopup="menu" data-testid="ask-ses-menu" @click="menu = !menu"><Icon name="more" small /></button>
          <div v-if="menu" class="menu-pop" role="menu">
            <button type="button" data-testid="ask-ses-rename" @click="startRename"><Icon name="pencil" small />{{ $t('ask.ses.rename') }}</button>
            <button type="button" data-testid="ask-ses-share" @click="menu = false; emit('patch', { shared: !session.shared })"><Icon name="users" small />{{ session.shared ? $t('ask.ses.unshare') : $t('ask.ses.share') }}</button>
            <button type="button" data-testid="ask-ses-archive" @click="menu = false; emit('patch', { archived: !session.archived })"><Icon name="inbox" small />{{ session.archived ? $t('ask.ses.restore') : $t('ask.ses.archive') }}</button>
            <div class="sep" />
            <button type="button" class="danger" data-testid="ask-ses-delete" @click="confirmDelete"><Icon name="trash" small />{{ $t('ask.ses.delete') }}</button>
          </div>
        </span>
      </span>
    </div>

    <div v-if="repOpen" class="modal-back" @click.self="repOpen = false">
      <div class="modal rep" role="dialog" aria-modal="true" data-testid="ask-ai-report">
        <div class="modal-h">
          <h2><Icon name="spark" small /> {{ $t('ask.dl.aiTitle') }}</h2>
          <span v-if="rep" class="vsum"><span class="vs ok">{{ $t('ask.dl.nVerified', { n: rep.verified }) }}</span><span v-if="rep.unverified" class="vs fix">{{ $t('ask.dl.nUnverified', { n: rep.unverified }) }}</span></span>
          <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="repOpen = false"><Icon name="x" /></button>
        </div>
        <div class="modal-b rep-b">
          <p v-if="repBusy" class="muted">{{ $t('ask.dl.aiBusy') }}</p>
          <div v-else-if="repErr" class="notice err"><Icon name="err" /><div class="grow">{{ repErr }}</div></div>
          <template v-else-if="rep">
            <template v-for="(b, i) in rep.blocks" :key="i">
              <h4 v-if="b.type === 'h'">{{ b.segments.map((s) => s.text).join(' ') }}</h4>
              <component :is="b.type === 'li' ? 'li' : 'p'" v-else><template v-for="(s, k) in b.segments" :key="k"><span v-if="s.ok">{{ s.text }}</span><span v-else class="unv" :title="$t('ask.dl.unvTip')">{{ s.text }}</span>{{ ' ' }}</template></component>
            </template>
          </template>
        </div>
        <div class="modal-f">
          <span class="small faint">{{ $t('ask.dl.aiNote') }}</span>
          <span class="grow" />
          <button class="btn btn-sm" type="button" @click="repOpen = false">{{ $t('c.close') }}</button>
          <button class="btn btn-sm btn-primary" type="button" :disabled="!rep" data-testid="ask-ai-report-save" @click="saveMd"><Icon name="download" small />{{ $t('ask.dl.saveMd') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sh { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; padding: 10px 14px; border-bottom: 1px solid var(--line); }
.sh .title { font-size: 15px; font-weight: 650; color: var(--ink); }
.title-in { font-size: 14px; font-weight: 600; padding: 3px 8px; min-width: 260px; flex: 1; max-width: 480px; }
.acts { margin-left: auto; display: inline-flex; gap: 6px; align-items: center; }
.rel { position: relative; }
.tag.shared { background: var(--teal-soft); color: var(--teal-ink); border: 1px solid var(--teal-line); }
.ro-banner { display: flex; gap: 8px; align-items: center; padding: 8px 14px; font-size: 12.5px; background: var(--amber-soft); color: var(--amber-ink); border-bottom: 1px solid var(--amber-line); }
.menu-pop { position: absolute; right: 0; top: 100%; margin-top: 4px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow-pop); padding: 4px; min-width: 300px; z-index: 30; }
.menu-pop .h { font-size: 11px; color: var(--ink-3); padding: 6px 10px 2px; }
.menu-pop button, .menu-pop a { display: flex; width: 100%; gap: 8px; align-items: center; padding: 7px 10px; background: none; border: 0; font: inherit; font-size: 13px; color: var(--ink); cursor: pointer; border-radius: 6px; text-align: left; text-decoration: none; box-sizing: border-box; }
.menu-pop button:hover, .menu-pop a:hover { background: var(--surface-2); }
.menu-pop .k { margin-left: auto; font-size: 11.5px; color: var(--ink-3); }
.menu-pop .danger { color: var(--red-ink); }
.menu-pop .sep { height: 1px; background: var(--line); margin: 4px 0; }
.rep { width: min(760px, calc(100vw - 32px)); max-height: 82vh; display: flex; flex-direction: column; }
.modal-h { gap: 10px; }
.modal-h h2 { display: inline-flex; gap: 6px; align-items: center; }
.vsum { display: inline-flex; gap: 6px; margin-left: auto; }
.rep-b { overflow: auto; font-size: 13.5px; line-height: 1.75; }
.rep-b h4 { margin: 12px 0 4px; font-size: 14px; }
.rep-b li { margin-left: 18px; }
.unv { background: var(--amber-soft); border-bottom: 1px dashed var(--amber-ink); }
.modal-f { display: flex; gap: 8px; align-items: center; padding: 10px 16px; border-top: 1px solid var(--line); }
.grow { flex: 1; }
</style>
