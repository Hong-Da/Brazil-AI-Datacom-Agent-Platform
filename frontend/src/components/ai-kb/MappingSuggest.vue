<script setup lang="ts">
/**
 * 映射建议（M8-5，预览 DevelopDocs/ui-preview/M8/kb.html“映射建议”）：在 Schema 视图页打开的对话框。
 * 选平台族（可选功能域），skill mapping-suggest 为还没有映射的命令卡建议 Schema 节点；scope mapping:<平台族>。
 * 每条先由代码跑知识库校验、往返（该平台族全部样本）、翻译回归三项检查（卡片里显示）；采纳 = 送审核队列（card_maps）。
 * 左侧表格按建议列出命令卡与建议的节点（不在页面写死“还有几张没映射”：没有对应接口）。
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { errorText, get } from '@/api'
import Icon from '@/components/Icon.vue'
import AiEntryButton from '@/components/ai-suggest/AiEntryButton.vue'
import AiSuggestPanel from '@/components/ai-suggest/AiSuggestPanel.vue'
import { projectPath, query, type ListResult } from '@/components/ai-suggest/logic'
import { useProject } from '@/stores/project'
import { mappingScope, mapRows, type MapRow } from './logic'

const props = withDefaults(defineProps<{ initialFamily?: string }>(), { initialFamily: '' })
const emit = defineEmits<{ close: [] }>()
const project = useProject()
const families = ref<string[]>([])
const domains = ref<string[]>([])
const family = ref('')
const domain = ref('')
const loadErr = ref('')
const rows = ref<MapRow[]>([])
const state = ref('loading')
const panel = ref<InstanceType<typeof AiSuggestPanel> | null>(null)
const params = computed(() => (domain.value ? { family: family.value, domain: domain.value } : { family: family.value }))
const scope = computed(() => mappingScope(family.value))

async function load(): Promise<void> {
  loadErr.value = ''
  try {
    await project.ensure()
    const p = await get<{ families: string[] }>('/kb/profiles')
    const s = await get<{ domains: { domain: string }[] }>('/kb/schema')
    families.value = p.families ?? []
    domains.value = (s.domains ?? []).map((d) => d.domain)
    family.value = families.value.includes(props.initialFamily) ? props.initialFamily : families.value[0] ?? ''
    await loadRows()
  } catch (e) {
    loadErr.value = errorText(e)
  }
}
async function loadRows(): Promise<void> {
  rows.value = []
  if (!project.ref || !family.value) return
  try {
    const r = await get<ListResult>(projectPath(project.ref, `/ai/suggestions${query({ skill: 'mapping-suggest', scope: scope.value, limit: 200 })}`))
    rows.value = mapRows(r.items)
  } catch { /* 表格只是汇总，取不到时面板里仍能看到建议 */ }
}
function onState(s: string): void {
  state.value = s
  if (s === 'done' || s === 'empty') void loadRows()
}
async function run(): Promise<void> {
  await nextTick()
  await panel.value?.start()
}
onMounted(load)
</script>

<template>
  <div class="modal-back" data-testid="map-dialog" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div class="modal ms" role="dialog" aria-modal="true">
      <div class="modal-h">
        <h2><Icon name="map" small /> {{ $t('kb-ai.ms.title') }}</h2>
        <button class="btn btn-ghost btn-sm" type="button" data-testid="map-close" @click="emit('close')"><Icon name="x" small /></button>
      </div>
      <div class="modal-b">
        <div v-if="loadErr" class="notice err"><Icon name="err" /><div class="grow small">{{ loadErr }}</div><button class="btn btn-xs" type="button" @click="load">{{ $t('c.retry') }}</button></div>
        <div v-else-if="!project.ref" class="notice warn"><Icon name="warn" /><div class="grow small">{{ $t('kb-ai.needProject') }}</div></div>
        <template v-else>
          <div class="toolbar">
            <label class="row small" style="gap: 6px">{{ $t('kb-ai.ms.family') }}
              <select v-model="family" class="select mono" data-testid="map-family" @change="loadRows">
                <option v-for="f in families" :key="f" :value="f">{{ f }}</option>
              </select>
            </label>
            <label class="row small" style="gap: 6px">{{ $t('kb-ai.ms.domain') }}
              <select v-model="domain" class="select mono" data-testid="map-domain">
                <option value="">{{ $t('kb-ai.ms.allDomains') }}</option>
                <option v-for="d in domains" :key="d" :value="d">{{ d }}</option>
              </select>
            </label>
            <span class="grow" />
            <AiEntryButton v-if="family" :skills="['mapping-suggest']" :busy="state === 'running'" small @run="run" />
          </div>
          <p class="small faint">{{ $t('kb-ai.ms.sub') }}</p>
          <div v-if="family" class="hostgrid">
            <section class="panel">
              <div class="panel-h"><h3>{{ $t('kb-ai.ms.tableT', { f: family }) }}</h3></div>
              <div class="tbl-wrap">
                <table class="tbl mp" data-testid="map-table">
                  <thead><tr><th>{{ $t('kb-ai.ms.card') }}</th><th>{{ $t('kb-ai.ms.mapsTo') }}</th></tr></thead>
                  <tbody>
                    <tr v-if="!rows.length"><td colspan="2"><div class="empty"><p>{{ $t('kb-ai.ms.noRows') }}</p></div></td></tr>
                    <tr v-for="r in rows" :key="r.card" data-testid="map-row" :data-state="r.state">
                      <td class="mono small cmd">{{ r.card }}</td>
                      <td>
                        <span v-for="n in r.nodes" :key="n" :class="r.state === 'fail' ? 'vchip fail' : r.state === 'sent' ? 'srcchip s-ai' : 'srcchip s-pending'">
                          <Icon :name="r.state === 'fail' ? 'err' : 'spark'" small />{{ n }}
                        </span>
                        <span v-if="r.state === 'sent'" class="small faint">{{ $t('kb-ai.ut.sent') }}</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
            <AiSuggestPanel ref="panel" :key="scope" skill="mapping-suggest" :params="params" :scope="scope" @state="onState" @changed="loadRows" />
          </div>
          <div v-else class="empty"><p>{{ $t('kb-ai.ms.noFamily') }}</p></div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ms { width: min(1180px, 100%); max-height: calc(100vh - 96px); display: flex; flex-direction: column; }
.ms .modal-b { overflow: auto; display: flex; flex-direction: column; gap: 10px; }
.hostgrid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(380px, 460px); gap: 12px; align-items: start; }
@media (max-width: 1000px) { .hostgrid { grid-template-columns: minmax(0, 1fr); } }
.mp td { vertical-align: top; }
.mp td > span { margin: 0 4px 4px 0; }
.cmd { overflow-wrap: anywhere; }
.srcchip { display: inline-flex; align-items: center; gap: 4px; height: 20px; padding: 0 7px; border-radius: 4px; font: 11.5px var(--font-mono); color: var(--violet); border: 1px dashed var(--ai-line); background: var(--surface); }
.srcchip.s-ai { border-style: solid; background: var(--ai-soft); }
</style>
