<script setup lang="ts">
/**
 * 统一的 AI 入口按钮（M8-2，预览 suggest.html“入口”）：主按钮运行本页最常用的 skill，▾ 里列出本页能用的 skill。
 * 运行中显示进度、不能重复发起；AI 不可用时按钮变灰但仍可点，点开显示原因与去处（REQ-040 的 ai-off-hint）。
 * 用法：<AiEntryButton :skills="['device-summary']" :busy="running" @run="(id) => panel.start()" />
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { get } from '@/api'
import Icon from '@/components/Icon.vue'
import AiOffHint from '@/components/ai-off-hint.vue'
import { useProject } from '@/stores/project'
import { pick, projectPath, type SkillList } from './logic'
import './ai-suggest.css'

const props = withDefaults(defineProps<{ skills: string[]; busy?: boolean; small?: boolean; label?: string }>(), { busy: false, small: false, label: '' })
const emit = defineEmits<{ run: [skill: string] }>()
const { t, locale } = useI18n()
const T = (k: string) => t(`ai-suggest.${k}`)
const project = useProject()

const info = ref<SkillList | null>(null)
const menu = ref(false)
const root = ref<HTMLElement | null>(null)
const off = computed(() => !!info.value && !info.value.ai.configured)
const list = computed(() => props.skills.map((id) => info.value?.skills.find((s) => s.id === id)).filter((s) => !!s))
const main = computed(() => list.value.find((s) => s.enabled) ?? null)

async function load(): Promise<void> {
  if (!project.ref) return
  try { info.value = await get<SkillList>(projectPath(project.ref, '/ai/suggestions/skills')) } catch { info.value = null }
}
function clickMain(): void {
  if (off.value || !main.value) { menu.value = !menu.value; return }
  if (!props.busy) emit('run', main.value.id)
}
function pickSkill(id: string): void {
  menu.value = false
  if (!props.busy) emit('run', id)
}
function outside(e: MouseEvent): void {
  if (menu.value && root.value && !root.value.contains(e.target as Node)) menu.value = false
}
onMounted(() => { void load(); document.addEventListener('click', outside) })
onBeforeUnmount(() => document.removeEventListener('click', outside))
defineExpose({ reload: load })
</script>

<template>
  <span ref="root" class="aib" :class="{ 'is-busy': busy, 'is-off': off }" data-testid="ai-entry" :data-off="off">
    <button class="btn main" :class="{ 'btn-sm': small }" type="button" data-testid="ai-entry-main" @click="clickMain">
      <span v-if="busy" class="spin" /><Icon v-else name="spark" small />
      <span>{{ busy ? T('busy') : label || T('btn') }}</span>
      <span v-if="off" class="offdot">{{ T('off') }}</span>
    </button>
    <button class="btn more" :class="{ 'btn-sm': small }" type="button" :aria-expanded="menu" data-testid="ai-entry-more" @click="menu = !menu"><Icon name="chevD" small /></button>
    <div v-if="menu" class="aimenu" :class="{ off }" role="menu" data-testid="ai-entry-menu">
      <AiOffHint v-if="off" :reason="info?.ai.reason ?? null" />
      <template v-else>
        <div class="mh"><Icon name="plug" small />{{ T('menuHead') }}</div>
        <button v-for="s in list" :key="s.id" type="button" role="menuitem" :disabled="!s.enabled || busy" :data-testid="`ai-entry-${s.id}`" @click="pickSkill(s.id)">
          <Icon name="spark" small /><b>{{ pick(s.title, String(locale)) }}</b>
          <span>{{ s.enabled ? pick(s.description, String(locale)) : T('disabled') }}</span>
        </button>
        <div class="mf"><Icon name="info" small />{{ T('menuFoot') }}</div>
      </template>
    </div>
  </span>
</template>
