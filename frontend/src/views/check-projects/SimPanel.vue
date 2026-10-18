<script setup lang="ts">
/** 工作区右下：变更脚本的模拟执行结果 / 完整配置与基线的差异（按有效值）。 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { useTerms } from '@/stores/terms'
import { semValue } from './logic'
import type { CheckResult, Kind } from './types'

const props = defineProps<{ result: CheckResult | null; kind: Kind }>()
const emit = defineEmits<{ (e: 'diff-baseline'): void; (e: 'line', n: number): void }>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`check-projects.${k}`, p ?? {})
const terms = useTerms()

const r = computed(() => props.result?.result ?? null)
const base = computed(() => props.result?.baseline ?? null)
const removed = computed(() => r.value?.removed ?? [])
const cmp = computed(() => r.value?.compare ?? null)
const DK: Record<string, string> = { added: 'added', removed: 'removed', changed: 'modified', renamed: 'renamed' }
const label = (d: { label?: string; node: string }) => d.label || terms.describe(d.node)
</script>

<template>
  <section class="panel sim" data-testid="cp-sim">
    <div class="panel-h">
      <h3>{{ kind === 'change' ? T('sim.title') : T('sim.fullTitle') }}</h3>
      <span v-if="base" class="meta small faint mono">{{ base.label }}</span>
    </div>
    <div class="sb">
      <div v-if="!result" class="small faint">{{ $t('c.loading') }}</div>
      <div v-else-if="result.kind !== kind" class="small faint">{{ T('sim.pending') }}</div>
      <template v-else-if="kind === 'change' && r">
        <div class="simnums" data-testid="cp-simnums">
          <div><div class="n add">+{{ r.lines_added ?? 0 }}</div><div class="k">{{ T('sim.added') }}</div></div>
          <div><div class="n del">−{{ r.lines_removed ?? 0 }}</div><div class="k">{{ T('sim.removed') }}</div></div>
          <div><div class="n ovr">~{{ r.lines_overridden ?? 0 }}</div><div class="k">{{ T('sim.overridden') }}</div></div>
          <div><div class="n side">↻{{ r.side_effect_removed ?? 0 }}</div><div class="k">{{ T('sim.sideRemoved') }}</div></div>
        </div>
        <div class="simk">{{ T('sim.removedLines') }} <span class="faint">{{ removed.length }}</span></div>
        <div v-if="removed.length" class="simlines">
          <div v-for="(x, i) in removed" :key="i" :title="T('sim.byLine', { n: x.by })">
            <span class="bn">{{ T('sim.baseLine', { n: x.base_line }) }}</span><span class="bt" :class="x.how">{{ x.text }}</span>
            <span class="note"><span class="cat" :class="`c-${x.how === 'side_effect' ? 'side_effect' : x.how}`">{{ T(`how.${x.how}`) }}</span> <a href="#" @click.prevent="emit('line', x.by)">{{ T('sim.byLine', { n: x.by }) }}</a></span>
          </div>
        </div>
        <div v-else class="small faint">{{ T('none') }}</div>
        <div class="simk">{{ T('sim.afterCheck') }}</div>
        <div v-if="(r.findings_new?.length ?? 0) + (r.findings_fixed?.length ?? 0)" class="findl">
          <div v-for="(f, i) in r.findings_new" :key="`n${i}`"><span class="sym new">+</span><span>{{ f.text }}<span class="mono faint" style="font-size: 11px"> {{ f.rule }}</span></span></div>
          <div v-for="(f, i) in r.findings_fixed" :key="`g${i}`"><span class="sym gone">−</span><span>{{ f.text }}</span></div>
        </div>
        <div v-else class="small faint">{{ T('sim.noFindings') }}</div>
        <div class="small faint">{{ T('sim.finalLines', { n: r.final_lines ?? 0, u: r.unknown ?? 0 }) }}</div>
      </template>
      <template v-else-if="kind === 'full' && r">
        <div class="small muted">{{ T('sim.fullStats', { f: r.findings_total ?? 0, u: r.unknown ?? 0, raw: r.raw ?? 0 }) }}</div>
        <template v-if="cmp">
          <div class="diffsum">
            <span v-for="(n, k) in cmp.summary.by_kind" :key="k" class="dk" :class="DK[k] || k">{{ T(`dk.${k}`) }} {{ n }}</span>
            <button class="btn btn-xs" type="button" style="margin-left: auto" data-testid="cp-sim-diff" @click="emit('diff-baseline')"><Icon name="compare" small />{{ T('textDiff') }}</button>
          </div>
          <div v-if="cmp.summary.by_kind.removed" class="notice warn"><Icon name="warn" /><div>{{ T('sim.fullRemoved', { n: cmp.summary.by_kind.removed }) }}</div></div>
          <div v-if="cmp.equal" class="small faint">{{ T('sim.fullEqual') }}</div>
          <template v-else>
            <div class="simk">{{ T('sim.objChanges') }} <span class="faint">{{ cmp.diffs.length }}</span></div>
            <div class="objl">
              <div v-for="(d, i) in cmp.diffs.slice(0, 60)" :key="i">
                <span class="dk" :class="DK[d.kind] || d.kind">{{ T(`dk.${d.kind}`) }}</span><code>{{ label(d) }}</code>
                <span class="sub"><template v-if="d.a && d.b">{{ semValue(d.a.value) }} → {{ semValue(d.b.value) }}</template><template v-else-if="d.b">{{ semValue(d.b.value) }}</template><template v-else-if="d.a">{{ semValue(d.a.value) }}</template></span>
              </div>
              <div v-if="cmp.diffs.length > 60" class="small faint">+{{ cmp.diffs.length - 60 }}</div>
            </div>
          </template>
        </template>
        <div v-else class="small faint">{{ T('sim.noBaseline') }}</div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.simlines .bt.undo, .simlines .bt.override { text-decoration-color: var(--ink-3); }
.simlines .note a { color: var(--blue-ink); }
.simlines > div { grid-template-columns: auto minmax(0, 1fr); }
.simlines .bn { overflow: visible; }
</style>
