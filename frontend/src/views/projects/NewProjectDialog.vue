<script setup lang="ts">
/** 新建项目（预览 projects.html 的“新建项目”对话框）：名称、标识（可选）、说明、默认显示风格、翻译规则集。 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { ApiError, errorText, get, post } from '@/api'
import { pickLang } from '@/i18n'
import { usePrefs } from '@/stores/prefs'
import { useTerms } from '@/stores/terms'
import type { ProjectRow } from '@/stores/project'
import { projectBody, suggestSlug, validSlug } from './logic'

const emit = defineEmits<{ (e: 'close'): void; (e: 'created', p: ProjectRow): void }>()
const { t, te } = useI18n()
const prefs = usePrefs()
const terms = useTerms()

const name = ref('')
const slug = ref('')
const slugTouched = ref(false)
const desc = ref('')
const style = ref('')
const ruleSet = ref('')
const ruleSets = ref<{ id: string; title: Record<string, string> | null }[]>([])
const tried = ref(false)
const busy = ref(false)
const error = ref('')
const nameEl = ref<HTMLInputElement | null>(null)

const nameErr = computed(() => tried.value && !name.value.trim())
const slugErr = computed(() => !!slug.value.trim() && !validSlug(slug.value.trim()))
const styleLabel = (s: string) => (te(`style.${s}`) ? t(`style.${s}`) : s)

watch(name, (v) => { if (!slugTouched.value) slug.value = suggestSlug(v) })

onMounted(async () => {
  await nextTick()
  nameEl.value?.focus()
  try {
    ruleSets.value = (await get<{ items: { id: string; title: Record<string, string> | null }[] }>('/translate-rules')).items
  } catch { /* 规则集取不到时只能选“不指定” */ }
})

async function create(): Promise<void> {
  tried.value = true
  if (nameErr.value || slugErr.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const settings: Record<string, string> = {}
    if (style.value) settings.style = style.value
    if (ruleSet.value) settings.rule_set = ruleSet.value
    const body = projectBody(name.value, slug.value, { description: desc.value, settings })
    emit('created', await post<ProjectRow>('/projects', body))
  } catch (e) {
    // 标识按属主唯一：409 表示自己已有同名项目（别人有同名的不影响）
    const s = slug.value.trim().toLowerCase()
    error.value = e instanceof ApiError && e.status === 409 && s ? t('projects.dlg.slugTaken', { s }) : errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="modal-back" data-testid="project-new-modal" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div class="modal" style="width: min(620px, 100%)" role="dialog" aria-modal="true" aria-labelledby="npT">
      <div class="modal-h">
        <h2 id="npT">{{ $t('projects.new') }}</h2>
        <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="emit('close')"><Icon name="x" /></button>
      </div>
      <div class="modal-b form-stack">
        <div class="form-grid">
          <div class="field">
            <label for="npName">{{ $t('projects.dlg.name') }}</label>
            <input id="npName" ref="nameEl" v-model="name" :class="['input', { 'is-error': nameErr }]" :placeholder="$t('projects.dlg.namePh')" maxlength="200" data-testid="np-name" @keydown.enter="create">
            <div v-if="nameErr" class="err"><Icon name="warn" small /><span>{{ $t('projects.dlg.nameErr') }}</span></div>
          </div>
          <div class="field">
            <label for="npSlug">{{ $t('projects.dlg.slug') }}</label>
            <input id="npSlug" v-model="slug" :class="['input mono', { 'is-error': slugErr }]" maxlength="64" data-testid="np-slug" @input="slugTouched = true">
            <div v-if="slugErr" class="err"><Icon name="warn" small /><span>{{ $t('projects.dlg.slugErr') }}</span></div>
            <div v-else class="hint">{{ $t('projects.dlg.slugHint') }}</div>
          </div>
          <div class="field span2">
            <label for="npDesc">{{ $t('projects.dlg.desc') }}</label>
            <textarea id="npDesc" v-model="desc" class="textarea" rows="2" maxlength="4000" />
          </div>
          <div class="field">
            <span class="field-label">{{ $t('projects.dlg.style') }}</span>
            <div class="seg" role="group">
              <button type="button" :aria-pressed="style === ''" @click="style = ''">{{ $t('projects.dlg.styleNone') }}</button>
              <button v-for="s in terms.styles" :key="s" type="button" :aria-pressed="style === s" @click="style = s">{{ styleLabel(s) }}</button>
            </div>
          </div>
          <div class="field">
            <label for="npRs">{{ $t('projects.dlg.ruleSet') }}</label>
            <select id="npRs" v-model="ruleSet" class="select">
              <option value="">{{ $t('projects.dlg.ruleSetNone') }}</option>
              <option v-for="r in ruleSets" :key="r.id" :value="r.id">{{ pickLang(r.title, prefs.lang) || r.id }}</option>
            </select>
          </div>
        </div>
        <div class="notice info"><Icon name="info" /><div>{{ $t('projects.dlg.newNote') }}</div></div>
        <div v-if="error" class="notice err" data-testid="np-error"><Icon name="err" /><div>{{ error }}</div></div>
      </div>
      <div class="modal-f">
        <span class="small faint" style="margin-right: auto">{{ $t('projects.dlg.newFoot') }}</span>
        <button class="btn" type="button" @click="emit('close')">{{ $t('c.cancel') }}</button>
        <button class="btn btn-primary" type="button" :disabled="busy" data-testid="np-create" @click="create">{{ busy ? $t('projects.busy') : $t('projects.dlg.create') }}</button>
      </div>
    </div>
  </div>
</template>
