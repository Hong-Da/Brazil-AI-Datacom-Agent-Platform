<script setup lang="ts">
/**
 * AI 结果的反馈按钮（REQ-033，预览 DevelopDocs/ui-preview/REQ-033/feedback.html）：有帮助 / 没帮助 / 更正（写出正确的内容）。
 * 提交到 POST /ai/skills/feedback {run_id, rating, correction}；一次调用只保留一条反馈，再点会覆盖，撤销即清除。
 * 点踩后可补充“哪里不对”（作为更正一并提交）。所有登录账号可用；管理员另有“在 skill 中查看”的链接。
 * kind：answer（AI 查询的回答）/ config（AI 生成的配置）/ finding（配置检查项目的 AI 发现）；mini 只显示图标。
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText, post } from '@/api'
import { useAuth } from '@/stores/auth'
import '@/styles/req033.css'

const props = defineProps<{ runId: number; skill?: string; kind?: 'answer' | 'config' | 'finding'; mini?: boolean; boxed?: boolean }>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`ai-skills.fb.${k}`, p ?? {})
const auth = useAuth()
const rating = ref<'up' | 'down' | 'corr' | null>(null)
const open = ref<'corr' | 'note' | null>(null)
const corr = ref('')
const noteText = ref('')
const err = ref('')
const busy = ref(false)
const kind = computed(() => props.kind ?? 'answer')
watch(() => props.runId, () => { rating.value = null; open.value = null; corr.value = ''; noteText.value = ''; err.value = '' })

async function send(r: 'up' | 'down' | null, correction: string): Promise<boolean> {
  busy.value = true
  err.value = ''
  try {
    await post('/ai/skills/feedback', { run_id: props.runId, rating: r, correction })
    return true
  } catch (e) {
    err.value = errorText(e)
    return false
  } finally { busy.value = false }
}
async function up(): Promise<void> {
  if (await send('up', '')) { rating.value = 'up'; open.value = null }
}
async function down(): Promise<void> {
  if (await send('down', '')) { rating.value = 'down'; open.value = 'note' }
}
async function sendNote(): Promise<void> {
  if (!noteText.value.trim()) { open.value = null; return }
  if (await send('down', noteText.value.trim())) open.value = null
}
async function sendCorr(): Promise<void> {
  if (!corr.value.trim()) { err.value = T('needText'); return }
  if (await send(null, corr.value.trim())) { rating.value = 'corr'; open.value = null }
}
async function undo(): Promise<void> {
  if (await send(null, '')) { rating.value = null; open.value = null; corr.value = ''; noteText.value = '' }
}
</script>

<template>
  <div class="r33fb" :class="{ mini, boxed }" data-testid="ai-feedback" :data-run="runId" :data-rating="rating ?? ''">
    <div class="fbrow">
      <span v-if="rating" class="fb-done" :class="rating" data-testid="fb-done">
        <Icon :name="rating === 'up' ? 'ok' : rating === 'down' ? 'thumbDown' : 'pencil'" small />
        <span>{{ T(`done.${rating}`) }}</span><span class="faint">·</span>
        <button type="button" class="undo" :disabled="busy" data-testid="fb-undo" @click="undo">{{ T('undo') }}</button>
      </span>
      <span v-else class="fb">
        <span v-if="!mini" class="fbq">{{ T('q') }}</span>
        <button type="button" class="fbb up" :disabled="busy" :title="T('up')" :aria-label="T('up')" data-testid="fb-up" @click="up"><Icon name="thumbUp" small /><span v-if="!mini">{{ T('up') }}</span></button>
        <button type="button" class="fbb down" :disabled="busy" :title="T('down')" :aria-label="T('down')" data-testid="fb-down" @click="down"><Icon name="thumbDown" small /><span v-if="!mini">{{ T('down') }}</span></button>
        <button type="button" class="fbb corr" :disabled="busy" :aria-pressed="open === 'corr'" :title="T('corr')" :aria-label="T('corr')" data-testid="fb-corr" @click="open = open === 'corr' ? null : 'corr'; err = ''"><Icon name="pencil" small /><span v-if="!mini">{{ T('corr') }}</span></button>
      </span>
      <span v-if="!mini" class="runinfo">
        <code v-if="skill">{{ skill }}</code><span>run #{{ runId }}</span>
        <router-link v-if="auth.isAdmin && skill" :to="{ name: 'ai-skill', params: { id: skill }, query: { tab: 'stats' } }">{{ T('viewSkill') }}</router-link>
      </span>
    </div>
    <div v-if="open === 'corr' && !rating" class="corrbox" data-testid="fb-corrbox">
      <label class="small" style="font-weight: 600">{{ T(`corrLabel.${kind}`) }}</label>
      <textarea v-model="corr" class="textarea" :class="{ 'is-error': err && !corr.trim() }" :rows="kind === 'config' ? 6 : 3" :placeholder="T(`corrPh.${kind}`)" data-testid="fb-corr-text" />
      <div class="row wrap" style="gap: 8px">
        <button type="button" class="btn btn-sm btn-primary" :disabled="busy" data-testid="fb-corr-send" @click="sendCorr">{{ T('sendCorr') }}</button>
        <button type="button" class="btn btn-sm" @click="open = null; err = ''">{{ $t('c.cancel') }}</button>
        <span class="small faint">{{ T('sanitized') }}</span>
      </div>
    </div>
    <div v-if="open === 'note' && rating === 'down'" class="fbmore">
      <textarea v-model="noteText" class="textarea" rows="2" :placeholder="T('notePh')" data-testid="fb-note" />
      <div class="row" style="gap: 8px">
        <button type="button" class="btn btn-sm" :disabled="busy" data-testid="fb-note-send" @click="sendNote">{{ T('sendNote') }}</button>
        <button type="button" class="btn btn-sm btn-ghost" @click="open = null">{{ T('skip') }}</button>
      </div>
    </div>
    <div v-if="err" class="fberr" data-testid="fb-error">{{ err }}</div>
  </div>
</template>
