<script setup lang="ts">
/**
 * 割接迁移页的“割接方案文档”（M8-4，预览 change.html 第二个页签）：AI 按代码生成的步骤起草各节（中英双语），
 * 右侧面板校验与采纳；左侧是方案预览——已采纳的实线、待采纳的紫色虚线、被拒绝或忽略的节显示“需要人工填写”，
 * 步骤里的命令由代码按引用填入。中文版与英文版分别下载（只含已采纳的部分）。
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { download, errorText, get } from '@/api'
import Icon from '@/components/Icon.vue'
import AiEntryButton from '@/components/ai-suggest/AiEntryButton.vue'
import AiSuggestPanel from '@/components/ai-suggest/AiSuggestPanel.vue'
import { projectPath, query, type ListResult } from '@/components/ai-suggest/logic'
import { useProject } from '@/stores/project'
import { cutoverParams, docLang, scopes, sectionState, type PlanDoc } from './logic'
import './ai-change.css'

const props = defineProps<{ body: Record<string, unknown> | null }>()
const { t, locale } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`ai-change.${k}`, p ?? {})
const project = useProject()

const panel = ref<InstanceType<typeof AiSuggestPanel> | null>(null)
const aiState = ref('loading')
const params = computed(() => cutoverParams(props.body))
const scope = computed(() => (params.value ? scopes.cutover(Number(params.value.device_id), String(params.value.to)) : ''))
const lang = ref<'zh-CN' | 'en'>(docLang(String(locale.value)))
const markAi = ref(true)
const doc = ref<PlanDoc | null>(null)
const err = ref('')
const P = (path: string) => projectPath(project.ref ?? '', path)

async function loadDoc(): Promise<void> {
  err.value = ''
  if (!scope.value || !project.ref) { doc.value = null; return }
  try {
    const r = await get<ListResult>(P(`/ai/suggestions${query({ skill: 'cutover-plan', scope: scope.value, limit: 1 })}`))
    const bid = r.items[0]?.batch_id
    doc.value = bid ? await get<PlanDoc>(P(`/ai/cutover-plan/${bid}?lang=${lang.value}`)) : null
  } catch (e) {
    err.value = errorText(e)
  }
}
async function dl(l: 'zh-CN' | 'en'): Promise<void> {
  if (!doc.value) return
  try {
    await download(P(`/ai/cutover-plan/${doc.value.batch_id}/export?lang=${l}`), `cutover-plan-${doc.value.batch_id}-${l}.md`)
  } catch (e) {
    err.value = errorText(e)
  }
}
watch([scope, lang], () => void loadDoc(), { immediate: true })
</script>

<template>
  <section class="mt16" data-testid="ai-cutover">
    <div v-if="!params" class="notice info"><Icon name="info" /><div class="grow">{{ T('planNeed') }}</div></div>
    <div v-else class="aic-grid">
      <section class="panel">
        <div class="aic-row" style="border-bottom: 1px solid var(--line)">
          <h3 style="font-size: 13.5px">{{ T('planT') }}</h3>
          <span class="ml-auto" />
          <div class="seg" role="group">
            <button type="button" :aria-pressed="lang === 'zh-CN'" data-testid="ai-cutover-zh" @click="lang = 'zh-CN'">中文</button>
            <button type="button" :aria-pressed="lang === 'en'" data-testid="ai-cutover-en" @click="lang = 'en'">English</button>
          </div>
          <label class="check small"><input v-model="markAi" type="checkbox"><span>{{ T('markAi') }}</span></label>
          <button class="btn btn-sm" type="button" :disabled="!doc" data-testid="ai-cutover-dl-zh" @click="dl('zh-CN')"><Icon name="download" small />{{ T('dlZh') }}</button>
          <button class="btn btn-sm" type="button" :disabled="!doc" data-testid="ai-cutover-dl-en" @click="dl('en')"><Icon name="download" small />{{ T('dlEn') }}</button>
          <AiEntryButton :skills="['cutover-plan']" :busy="aiState === 'running'" small @run="panel?.start()" />
        </div>
        <div v-if="err" class="notice err" style="margin: 10px"><Icon name="err" /><div class="grow small">{{ err }}</div></div>
        <div v-else-if="!doc" class="aic-empty">{{ T('planEmpty') }}</div>
        <div v-else class="aic-doc" :class="{ 'hide-ai': !markAi }" data-testid="ai-cutover-doc">
          <div><h2>{{ doc.title }}</h2><div class="meta">{{ doc.meta }}</div></div>
          <div class="small faint">{{ doc.note }}</div>
          <div v-for="(sec, i) in doc.sections" :key="sec.section" :data-section="sec.section" :data-state="sectionState(sec)">
            <h3>{{ i + 1 }}. {{ sec.title }}</h3>
            <div v-if="!sec.parts.length" class="missing">{{ T('missing') }}</div>
            <div v-for="p in sec.parts" :key="p.suggestion_id" class="ai-block" :class="{ 'is-ok': p.status === 'adopted' }" style="margin-bottom: 8px">
              <span class="ai-by"><Icon name="spark" small />{{ p.status === 'adopted' ? T('adopted') : T('pending') }}</span>
              <div>{{ p.text }}</div>
              <table v-if="p.steps.length" class="aic-steps mt8">
                <thead><tr><th>{{ T('colStep') }}</th><th>{{ T('colAction') }}</th><th>{{ T('colCmd') }}</th><th>{{ T('colCheck') }}</th></tr></thead>
                <tbody>
                  <tr v-for="(st, j) in p.steps" :key="j">
                    <td class="mono small">{{ st.step }}</td>
                    <td>{{ st.action || st.label }}</td>
                    <td><code v-for="(c, k) in st.commands" :key="k">{{ c }}</code><span v-if="!st.commands.length" class="faint">—</span></td>
                    <td>{{ st.check || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>
      <div class="aic-side">
        <AiSuggestPanel ref="panel" skill="cutover-plan" :params="params" :scope="scope" @state="aiState = $event" @changed="loadDoc" />
      </div>
    </div>
  </section>
</template>
