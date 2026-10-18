<script setup lang="ts">
/** 改名结果（REQ-032）：试运行、翻译、割接迁移共用。改名清单、端口映射、冲突、命名规范告警、原文中的旧名、知识缺口。 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import type { NamingReport, RuleRef } from './logic'

const props = defineProps<{ report: NamingReport; testid?: string }>()
const { t } = useI18n()
type Tab = 'renames' | 'ports' | 'conflicts' | 'naming' | 'other'
const tab = ref<Tab>(props.report.conflicts.length ? 'conflicts' : props.report.renames.length || !props.report.ports.length ? 'renames' : 'ports')
const open = ref<Record<string, boolean>>({})
const tabs = computed<{ k: Tab; n: number; tone?: string }[]>(() => [
  { k: 'renames', n: props.report.renames.length },
  { k: 'ports', n: props.report.ports.length },
  { k: 'conflicts', n: props.report.conflicts.length, tone: props.report.conflicts.length ? 'red' : '' },
  { k: 'naming', n: props.report.naming.length, tone: props.report.naming.length ? 'amber' : '' },
  { k: 'other', n: props.report.text_refs.length + props.report.gaps.length },
])
const ruleText = (r: RuleRef | null) => (r ? t(`translate-rules.ruleRef.${r.section}`, { n: r.index + 1 }) : t('translate-rules.ruleRef.fix'))
const s = computed(() => props.report.summary)
</script>

<template>
  <section class="panel nrp" :data-testid="testid ?? 'naming-report'">
    <div class="panel-h">
      <h2><Icon name="pencil" small />{{ $t('translate-rules.report') }}</h2>
      <span class="meta"><template v-if="report.rule_set !== 'unsaved'">{{ report.rule_set }}</template><template v-if="report.family"> · {{ report.family }}</template></span>
    </div>
    <div class="nsum">
      <div><b>{{ s.renamed }}</b><span>{{ $t('translate-rules.sum.renamed') }}</span></div>
      <div><b>{{ s.refs }}</b><span>{{ $t('translate-rules.sum.refs') }}</span></div>
      <div><b>{{ s.ports }}</b><span>{{ $t('translate-rules.sum.ports', { n: s.subinterfaces }) }}</span></div>
      <div :class="{ bad: s.conflicts }"><b>{{ s.conflicts }}</b><span>{{ $t('translate-rules.sum.conflicts') }}</span></div>
      <div :class="{ warn: s.naming }"><b>{{ s.naming }}</b><span>{{ $t('translate-rules.sum.naming') }}</span></div>
    </div>
    <div class="ntabs" role="tablist">
      <button v-for="x in tabs" :key="x.k" type="button" role="tab" :aria-selected="tab === x.k" :class="x.tone" :data-testid="`nr-tab-${x.k}`" @click="tab = x.k">
        {{ $t(`translate-rules.tab.${x.k}`) }}<span class="cnt">{{ x.n }}</span>
      </button>
    </div>
    <div class="nbody">
      <template v-if="tab === 'renames'">
        <div v-if="!report.renames.length" class="small faint pad">{{ $t('translate-rules.noRenames') }}</div>
        <table v-else class="tbl" data-testid="nr-renames">
          <thead><tr><th>{{ $t('translate-rules.col.type') }}</th><th>{{ $t('translate-rules.col.rename') }}</th><th>{{ $t('translate-rules.col.rule') }}</th><th>{{ $t('translate-rules.col.refs') }}</th><th>{{ $t('translate-rules.col.state') }}</th></tr></thead>
          <tbody>
            <template v-for="r in report.renames" :key="r.node">
              <tr :class="{ off: !r.applied }">
                <td class="mono small">{{ r.type }}</td>
                <td class="mono"><span class="old">{{ r.from }}</span> → <b class="new">{{ r.to }}</b><span v-if="r.mapped !== r.to" class="small faint"> ({{ r.mapped }})</span></td>
                <td class="small">{{ ruleText(r.rule) }}<span v-for="f in r.fixes" :key="f" class="tag t-blue xs">{{ $t(`translate-rules.fix.${f}`) }}</span></td>
                <td>
                  <button v-if="r.refs" class="btn btn-ghost btn-xs" type="button" @click="open = { ...open, [r.node]: !open[r.node] }"><Icon :name="open[r.node] ? 'chevD' : 'chevR'" small />{{ r.refs }}</button>
                  <span v-else class="faint">0</span>
                </td>
                <td><span v-if="r.applied" class="tag pass">{{ $t('translate-rules.applied') }}</span><span v-else class="tag fail">{{ $t(`translate-rules.conflict.${r.conflict}`) }}</span></td>
              </tr>
              <tr v-if="open[r.node]" class="refs">
                <td />
                <td colspan="4">
                  <div v-for="x in r.ref_nodes" :key="x.node" class="mono small">{{ x.node }}<span v-if="x.lines.length" class="faint"> @{{ x.lines.join(',') }}</span></div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </template>
      <template v-else-if="tab === 'ports'">
        <div v-if="!report.ports.length" class="small faint pad">{{ $t('translate-rules.noPorts') }}</div>
        <table v-else class="tbl" data-testid="nr-ports">
          <thead><tr><th>{{ $t('translate-rules.col.port') }}</th><th>{{ $t('translate-rules.col.rule') }}</th><th>{{ $t('translate-rules.col.subif') }}</th><th>{{ $t('translate-rules.col.state') }}</th></tr></thead>
          <tbody>
            <tr v-for="p in report.ports" :key="p.from" :class="{ off: !p.applied }">
              <td class="mono"><span class="old">{{ p.from }}</span> → <b class="new">{{ p.to }}</b></td>
              <td class="small">{{ ruleText(p.rule) }}</td>
              <td>{{ p.subinterfaces }}</td>
              <td><span v-if="p.applied" class="tag pass">{{ $t('translate-rules.applied') }}</span><span v-else class="tag fail">{{ $t('translate-rules.conflict.port_many_to_one') }}</span></td>
            </tr>
          </tbody>
        </table>
      </template>
      <template v-else-if="tab === 'conflicts'">
        <div v-if="!report.conflicts.length" class="small faint pad">{{ $t('translate-rules.noConflicts') }}</div>
        <ul v-else class="nlist" data-testid="nr-conflicts">
          <li v-for="(c, i) in report.conflicts" :key="i"><Icon name="err" small /><span>{{ $t(`translate-rules.conflictText.${c.kind}`, { type: c.type, to: c.to, from: c.from.join(', ') }) }}</span></li>
        </ul>
      </template>
      <template v-else-if="tab === 'naming'">
        <div v-if="!report.naming.length" class="small faint pad">{{ $t('translate-rules.noNaming') }}</div>
        <ul v-else class="nlist" data-testid="nr-naming">
          <li v-for="(w, i) in report.naming" :key="i" class="warn">
            <Icon name="warn" small />
            <span><span class="mono small">{{ w.type }}</span> {{ w.problem === 'length' ? $t('translate-rules.problem.length', { name: w.name, length: w.length ?? 0, max: w.max_length ?? 0 }) : $t('translate-rules.problem.pattern', { name: w.name, pattern: w.pattern ?? '' }) }}
              <span class="small faint">{{ w.fixed ? $t('translate-rules.fixedYet') : $t('translate-rules.notFixed') }}</span></span>
          </li>
        </ul>
      </template>
      <template v-else>
        <div v-if="!report.text_refs.length && !report.gaps.length" class="small faint pad">{{ $t('translate-rules.noOther') }}</div>
        <ul class="nlist">
          <li v-for="(x, i) in report.text_refs" :key="'t' + i"><Icon name="info" small /><span>{{ $t('translate-rules.textRef', { line: x.line, name: x.name, to: x.to }) }} <code>{{ x.text }}</code></span></li>
          <li v-for="(g, i) in report.gaps" :key="'g' + i"><Icon name="book" small /><span>{{ $t('translate-rules.gap', { type: g.type, family: g.family ?? '—' }) }}</span></li>
        </ul>
      </template>
    </div>
  </section>
</template>

<style scoped>
.nrp .panel-h h2 { display: inline-flex; align-items: center; gap: 6px; }
.nsum { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); border-bottom: 1px solid var(--line); }
.nsum > div { padding: 8px 14px; border-left: 1px solid var(--line); display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.nsum > div:first-child { border-left: 0; }
.nsum b { font: 600 19px/1.2 var(--font-display); }
.nsum span { font-size: 12px; color: var(--ink-2); }
.nsum .bad b { color: var(--red-ink); }
.nsum .warn b { color: var(--amber-ink); }
.ntabs { display: flex; gap: 2px; padding: 0 10px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.ntabs button { all: unset; cursor: pointer; padding: 8px 10px; font-size: 12.5px; color: var(--ink-2); border-bottom: 2px solid transparent; display: inline-flex; gap: 6px; align-items: center; }
.ntabs button[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--teal); font-weight: 600; }
.ntabs button:focus-visible { outline: 2px solid var(--focus); }
.ntabs .cnt { font-size: 11px; padding: 0 6px; border-radius: 9px; background: var(--surface-3); color: var(--ink-2); }
.ntabs .red .cnt { background: var(--red-soft); color: var(--red-ink); }
.ntabs .amber .cnt { background: var(--amber-soft); color: var(--amber-ink); }
.nbody { max-height: 420px; overflow: auto; }
.nbody .pad { padding: 14px; }
.nbody .tbl { width: 100%; }
.nbody tr.off td { color: var(--ink-3); }
.nbody .old { color: var(--ink-3); text-decoration: line-through; text-decoration-color: var(--line-strong); }
.nbody .new { color: var(--teal-ink); }
.nbody tr.refs td { background: var(--surface-2); }
.tag.xs { font-size: 10.5px; padding: 0 5px; margin-left: 4px; }
.nlist { list-style: none; margin: 0; padding: 6px 0; }
.nlist li { display: flex; gap: 8px; align-items: flex-start; padding: 6px 14px; font-size: 12.5px; border-top: 1px solid var(--line); }
.nlist li:first-child { border-top: 0; }
.nlist li :deep(.ico) { margin-top: 2px; flex: none; color: var(--ink-3); }
.nlist li.warn :deep(.ico) { color: var(--amber-ink); }
.nlist code { font: 11.5px var(--font-mono); color: var(--ink-2); overflow-wrap: anywhere; }
@media (max-width: 900px) { .nsum { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
