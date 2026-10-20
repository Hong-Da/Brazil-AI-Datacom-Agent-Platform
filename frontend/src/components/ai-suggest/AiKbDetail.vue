<script setup lang="ts">
/**
 * 知识库与脱敏类建议的内容（M8-5，预览 DevelopDocs/ui-preview/M8/compliance.html、kb.html）：
 * - kb_review / rule：规则 YAML 与样本试跑（代码）的命中；
 * - kb_review / unknown_card：归因、草稿命令卡字段、用草稿重新解析的结果；
 * - kb_review / card_maps：命令卡 → Schema 节点的映射与三项检查（知识库校验、往返、翻译回归）；
 * - sanitize_rule：行号、标出的文字（高亮）、补充的脱敏规则与出现次数。
 * 其他 kb_review 草稿按 JSON 显示。数据都来自后端（content 与 check.result）。
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { kbDetail, type Suggestion } from './logic'

const props = defineProps<{ item: Suggestion }>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`ai-suggest.${k}`, p ?? {})
const d = computed(() => kbDetail(props.item))
const CHK: Record<string, string> = { pass: 'ok', warn: 'warn', fail: 'err', skip: 'info' }
</script>

<template>
  <div class="kbd" data-testid="ai-kb-detail" :data-kind="d.kind">
    <template v-if="d.kind === 'rule'">
      <pre class="code-pre mono" data-testid="ai-kb-yaml">{{ d.yaml }}</pre>
      <div v-if="d.trial" class="trial" data-testid="ai-kb-trial">
        <div class="small faint"><Icon name="flask" small />{{ T('kb.trial', { n: d.trial.samples, h: d.trial.hits, s: d.trial.samples_hit, a: d.trial.applicable }) }}</div>
        <div v-if="!d.trial.hits" class="small faint">{{ T('kb.noHits') }}</div>
        <div v-for="(h, i) in d.trial.items" :key="i" class="hit">
          <span class="cv mono">{{ h.key || h.node }}</span><code class="small faint">{{ h.sample }}{{ h.line ? ` · L${h.line}` : '' }}</code>
        </div>
      </div>
    </template>

    <template v-else-if="d.kind === 'unknown_card'">
      <div class="row"><span class="tag">{{ T(`kb.cause.${d.cause}`) }}</span><span class="mono small">{{ d.target }}</span><span v-if="d.base" class="small faint">{{ T('kb.base', { id: d.base }) }}</span></div>
      <pre class="code-pre mono" data-testid="ai-kb-card">{{ d.cardText }}</pre>
      <div v-if="d.reparse" class="small" :class="d.reparse.recognized === d.reparse.lines ? 'okc' : 'faint'" data-testid="ai-kb-reparse">
        <Icon name="flask" small />{{ T('kb.reparse', { r: d.reparse.recognized, n: d.reparse.lines }) }}
      </div>
    </template>

    <template v-else-if="d.kind === 'card_maps'">
      <div class="row"><span class="mono small">{{ d.target }}</span></div>
      <div v-for="(m, i) in d.maps" :key="i" class="maprow" data-testid="ai-kb-map"><span class="cv mono">{{ m.node }}</span><code class="small">{{ m.expr || '—' }}</code></div>
      <div v-if="d.checks" class="checks3" data-testid="ai-kb-checks">
        <span v-for="k in ['kb', 'roundtrip', 'translate']" :key="k" class="vchip" :class="d.checks[k] === 'fail' ? 'fail' : d.checks[k] === 'skip' ? 'warn' : d.checks[k] ? 'pass' : ''">
          <Icon :name="CHK[d.checks[k] ?? ''] ?? 'info'" small />{{ T(`kb.chk.${k}`) }}
        </span>
      </div>
    </template>

    <template v-else-if="d.kind === 'sanitize'">
      <div class="sanl mono" data-testid="ai-kb-san">
        <span class="n">L{{ d.line }}</span>
        <span>{{ d.before }}<mark>{{ d.text }}</mark>{{ d.after }}</span>
      </div>
      <div class="small faint">
        <span class="tag">{{ T(`kb.san.${d.sanKind}`) }}</span>
        {{ T('kb.pattern') }} <code>{{ d.pattern }}</code>
        <template v-if="d.occurrences != null"> · {{ T('kb.occ', { n: d.occurrences }) }}</template>
      </div>
      <p v-if="d.explain" class="small">{{ d.explain }}</p>
    </template>

    <template v-else>
      <div class="small mono">{{ d.reviewKind }} · {{ d.target }}</div>
      <pre class="code-pre mono">{{ d.json }}</pre>
    </template>
  </div>
</template>

<style scoped>
.kbd { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.code-pre { margin: 0; padding: 8px 10px; border: 1px solid var(--line); border-radius: 5px; background: var(--surface); max-height: 240px; overflow: auto; font-size: 12px; white-space: pre; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.trial { display: flex; flex-direction: column; gap: 3px; }
.hit, .maprow { display: flex; gap: 8px; align-items: baseline; min-width: 0; font-size: 12px; }
.hit code, .maprow code { overflow-wrap: anywhere; }
.checks3 { display: flex; gap: 6px; flex-wrap: wrap; }
.okc { color: var(--teal-ink); }
.sanl { display: flex; gap: 8px; padding: 6px 8px; border-radius: 5px; background: var(--surface-2); font-size: 12px; overflow-wrap: anywhere; }
.sanl .n { color: var(--ink-3); }
.sanl mark { background: color-mix(in srgb, var(--violet-soft) 80%, transparent); color: var(--violet); border-radius: 2px; padding: 0 2px; }
</style>
