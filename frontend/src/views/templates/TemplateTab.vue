<script setup lang="ts">
/** 模板页签：正文（变量与块高亮）/ 模板文件（YAML，可编辑）、变量表、块与匹配方式。 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import M3Code from '@/components/m3-code.vue'
import { pickLang } from '@/i18n'
import { show } from '@/views/m3/texts'
import { bodyCode, varConstraint, varUses } from './logic'
import type { TemplateDetail } from './types'

const props = defineProps<{ detail: TemplateDetail | null; yaml: string; editing: boolean; isNew: boolean }>()
const emit = defineEmits<{ (e: 'update:yaml', v: string): void; (e: 'edit', v: boolean): void }>()
const { t, locale } = useI18n()
const view = ref<'body' | 'yaml'>('body')
const hot = ref<string | null>(null)

const shownView = computed(() => (props.editing || props.isNew || !props.detail ? 'yaml' : view.value))
const uses = computed(() => varUses(props.detail?.body ?? ''))
const blockTag = (b: { kind: string | null; block: string | null }) => `${t(b.kind === 'repeat' ? 'templates.repeat' : 'templates.optional')} · ${b.block}`
const code = computed(() => bodyCode(props.detail?.body ?? '', hot.value, new Map(), blockTag))
const title = (m: Record<string, string> | undefined) => pickLang(m, String(locale.value))
function toggleHot(v: string): void {
  hot.value = hot.value === v ? null : v
}
</script>

<template>
  <div class="ed">
    <div class="m3box">
      <div class="m3box-h">
        <h3>{{ $t('templates.text') }}</h3>
        <div v-if="detail && !isNew" class="seg" role="group">
          <button type="button" :aria-pressed="shownView === 'body'" :disabled="editing" data-testid="tpl-view-body" @click="view = 'body'">{{ $t('templates.viewBody') }}</button>
          <button type="button" :aria-pressed="shownView === 'yaml'" data-testid="tpl-view-yaml" @click="view = 'yaml'">YAML</button>
        </div>
        <span class="ml-auto" />
        <button v-if="!editing && !isNew" class="btn btn-xs" type="button" data-testid="tpl-edit" @click="emit('edit', true)"><Icon name="file" small />{{ $t('templates.edit') }}</button>
      </div>
      <M3Code v-if="shownView === 'body'" :lines="code" testid="tpl-body" class="tplcode" @var="toggleHot" />
      <textarea v-else-if="editing || isNew" class="yaml-ed mono" :value="yaml" spellcheck="false" data-testid="tpl-yaml" @input="emit('update:yaml', ($event.target as HTMLTextAreaElement).value)" />
      <pre v-else class="block yaml-ro">{{ yaml }}</pre>
      <div class="m3box-f">
        <template v-if="shownView === 'body'">
          <span class="row" style="gap: 6px"><span class="vx" style="cursor: default">var</span>{{ $t('templates.lgVar') }}</span>
          <span class="row" style="gap: 6px"><span class="blk-tag" style="margin: 0">{{ $t('templates.optional') }}</span>{{ $t('templates.lgOpt') }}</span>
          <span class="row" style="gap: 6px"><span class="blk-tag rep" style="margin: 0">{{ $t('templates.repeat') }}</span>{{ $t('templates.lgRep') }}</span>
          <span class="faint">{{ $t('templates.lgHint') }}</span>
        </template>
        <template v-else><Icon name="info" small /><span>{{ $t('templates.yamlNote') }}</span></template>
      </div>
    </div>

    <div class="stack" style="gap: 12px">
      <div class="m3box">
        <div class="m3box-h"><h3>{{ $t('templates.vars') }}</h3><span class="faint">{{ detail?.vars.length ?? 0 }}</span></div>
        <div class="tbl-wrap">
          <table class="tbl compact vt" data-testid="tpl-vars">
            <thead><tr><th>{{ $t('templates.vName') }}</th><th>{{ $t('templates.vType') }}</th><th>{{ $t('templates.vCons') }}</th><th>{{ $t('templates.vExample') }}</th></tr></thead>
            <tbody>
              <tr v-for="v in detail?.vars ?? []" :key="v.name" :class="{ 'is-sel': hot === v.name }" @click="toggleHot(v.name)">
                <td>
                  <span class="vname">{{ v.name }}</span>
                  <span v-if="v.block" class="bkk" :class="{ rep: detail?.blocks.find((b) => b.name === v.block)?.kind === 'repeat' }">{{ v.block }}</span>
                  <span v-if="v.derived" class="tag derived" style="height: 18px; margin-left: 4px">{{ $t('templates.derived') }}</span>
                  <div class="small faint">{{ title(v.title) }}<template v-if="uses.get(v.name)"> · {{ $t('templates.usedN', { n: uses.get(v.name) ?? 0 }) }}</template></div>
                </td>
                <td><span class="vtype">{{ v.type }}</span></td>
                <td class="cons">{{ varConstraint(v) || '—' }}</td>
                <td class="mono small">{{ v.default !== undefined ? show(v.default) : show(v.example) }}</td>
              </tr>
              <tr v-if="!detail?.vars.length"><td colspan="4" class="faint small">{{ $t('templates.noVars') }}</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      <div v-if="detail" class="m3box">
        <div class="m3box-h"><h3>{{ $t('templates.blocks') }}</h3><span class="faint">{{ detail.blocks.length }}</span></div>
        <div class="fixed-list">
          <template v-for="b in detail.blocks" :key="b.name">
            <span class="p">{{ b.name }}</span>
            <span>{{ title(b.title) }}</span>
            <span class="tag mono">{{ b.kind === 'repeat' ? `${$t('templates.repeat')} ${b.min ?? 0}..${b.max ?? '∞'}` : $t('templates.optional') }}</span>
          </template>
          <span v-if="!detail.blocks.length" class="faint" style="grid-column: 1 / -1">{{ $t('templates.noBlocks') }}</span>
        </div>
        <div class="m3box-f">
          <Icon name="info" small />
          <span>{{ $t('templates.matchInfo', { extra: detail.match.extra, scope: detail.match.extra_scope }) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ed { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); gap: 12px; align-items: start; }
@media (max-width: 1400px) { .ed { grid-template-columns: minmax(0, 1fr); } }
.tplcode { max-height: 640px; }
.yaml-ed { width: 100%; min-height: 520px; border: 0; border-radius: 0; padding: 10px 12px; font-size: 12px; line-height: 1.55; background: var(--surface); color: var(--ink); resize: vertical; outline: none; }
.yaml-ro { border: 0; border-radius: 0; max-height: 640px; margin: 0; overflow: auto; }
.vt td { vertical-align: top; }
.vt tr { cursor: pointer; }
.vt tr.is-sel td { background: var(--var-soft); }
.bkk { font-size: 11px; color: var(--var-ink); border: 1px dashed var(--var-line); border-radius: 3px; padding: 0 4px; white-space: nowrap; margin-left: 4px; }
.bkk.rep { border-style: double; border-width: 3px; }
.fixed-list { display: grid; grid-template-columns: max-content minmax(0, 1fr) max-content; gap: 6px 12px; font-size: 12px; padding: 10px 12px; align-items: center; }
.fixed-list .p { font-family: var(--font-mono); color: var(--var-ink); font-weight: 600; }
</style>
