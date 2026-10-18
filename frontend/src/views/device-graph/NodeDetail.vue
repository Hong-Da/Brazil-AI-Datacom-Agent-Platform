<script setup lang="ts">
/** 节点详情：取值与来源、Schema 与命令卡、所在行、依赖。 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { pickLang } from '@/i18n'
import { EDGE_SHORT, ancestors, lineRanges, nodeDeps, type Model } from './model'
import type { SchemaNodeInfo } from './types'

const props = defineProps<{
  model: Model
  id: string | null
  schema: Map<string, SchemaNodeInfo>
  profile: string | null
}>()
const emit = defineEmits<{ (e: 'pick', id: string): void; (e: 'line', n: number): void }>()
const { t, locale } = useI18n()

const node = computed(() => (props.id ? props.model.nodes.get(props.id) ?? null : null))
const path = computed(() => {
  if (!node.value) return ''
  return ancestors(props.model, node.value.id)
    .reverse()
    .slice(1)
    .map((a) => props.model.nodes.get(a)!.label)
    .join(' › ')
})
const ranges = computed(() => (node.value ? lineRanges(node.value.lines) : []))
const deps = computed(() => (node.value ? nodeDeps(props.model, node.value.id) : { out: [], in: [] }))
const info = computed(() => (node.value?.schema ? props.schema.get(node.value.schema) ?? null : null))
const rawForm = computed(() => {
  const a = node.value?.api
  if (!a || a.raw === undefined || a.raw === null) return ''
  const r = typeof a.raw === 'string' ? a.raw : JSON.stringify(a.raw)
  const v = typeof a.value === 'string' ? a.value : JSON.stringify(a.value)
  return r === v ? '' : r
})
const SRC = ['explicit', 'default', 'inherited', 'derived']

function nameOf(id: string): string {
  const n = props.model.nodes.get(id)
  if (!n) return id
  if (n.kind === 'attr' || n.kind === 'ext') {
    const p = n.parent ? props.model.nodes.get(n.parent) : undefined
    return p && p.kind !== 'domain' ? `${p.label} › ${n.label}` : n.label
  }
  return n.label
}
function edgeName(kind: string): string {
  const s = EDGE_SHORT[kind]
  return s === 'contains' ? t('device-graph.e.contains') : t(`e.${s ?? 'ref'}`)
}
</script>

<template>
  <aside class="panel p-detail" aria-label="Details" data-testid="node-detail">
    <div class="panel-h">
      <h3>{{ $t('device-graph.details') }}</h3>
      <span v-if="node" class="meta">{{ $t(`device-graph.k.${node.kind}`) }}</span>
    </div>
    <div class="d-scroll">
      <div v-if="!node" class="empty"><p>{{ $t('device-graph.pickHint') }}</p></div>
      <template v-else>
        <!-- 未识别行 -->
        <template v-if="node.kind === 'unknown'">
          <div class="notice err">
            <Icon name="unknown" />
            <div class="grow">
              <b>{{ $t('device-graph.unknownTitle', { n: node.lines[0] }) }}</b>
              <div class="small mt8 mono">{{ node.value }}</div>
            </div>
          </div>
          <dl class="kv mt12">
            <dt>{{ $t('device-graph.view') }}</dt><dd class="mono">{{ path || '—' }}</dd>
            <dt>{{ $t('device-graph.domain') }}</dt><dd class="mono">{{ node.domain }}</dd>
            <dt>{{ $t('device-graph.reason') }}</dt><dd>{{ $t('device-graph.unknownReason') }}</dd>
          </dl>
          <p class="small muted mt12">{{ $t('device-graph.unknownKeep') }}</p>
          <div class="row mt12">
            <router-link class="btn btn-sm btn-primary" :to="{ name: 'unknown-lines' }" data-testid="goto-unknown">{{ $t('device-graph.handleUnknown') }}</router-link>
          </div>
        </template>

        <template v-else>
          <div class="row wrap" style="gap: 6px">
            <span v-if="node.kind === 'attr' || node.kind === 'object' || node.kind === 'ext'" class="tag" :class="SRC.includes(node.origin) ? node.origin : ''">
              {{ SRC.includes(node.origin) ? $t(`src.${node.origin}`) : node.origin }}
            </span>
            <span v-if="node.api?.negated" class="tag t-amber">{{ $t('device-graph.negated') }}</span>
          </div>
          <div class="d-name mt8" :title="node.id" data-testid="detail-name">{{ node.kind === 'raw' ? node.value.trim() : node.label }}</div>
          <div v-if="path" class="small faint mono path">{{ path }}</div>

          <div v-if="node.kind === 'attr' || node.kind === 'ext'" class="d-val" :class="{ dashed: node.origin !== 'explicit', 'hid-default': node.origin === 'default', 'hid-derived': node.origin === 'derived' }">
            <div class="lbl">{{ $t('device-graph.value') }}</div>
            <div class="v">{{ node.value }}</div>
            <div v-if="rawForm" class="small muted mt8">{{ $t('device-graph.rawForm') }}: <span class="mono">{{ rawForm }}</span></div>
            <div v-if="node.origin === 'default'" class="small muted mt8" data-testid="default-note">{{ $t('device-graph.note.defaultFrom', { p: profile || '—' }) }}</div>
            <div v-else-if="node.origin !== 'explicit' && SRC.includes(node.origin)" class="small muted mt8">{{ $t(`device-graph.note.${node.origin}`) }}</div>
            <div v-if="node.kind === 'ext'" class="small muted mt8">{{ $t('device-graph.note.ext') }}</div>
          </div>
          <div v-else-if="node.kind === 'object' && (node.origin === 'default' || node.origin === 'derived')" class="d-val" :class="node.origin === 'default' ? 'hid-default' : 'hid-derived'">
            <div class="small muted" data-testid="default-note">{{ node.origin === 'default' ? $t('device-graph.note.defaultFrom', { p: profile || '—' }) : $t('device-graph.note.derived') }}</div>
          </div>
          <div v-else-if="node.kind === 'raw' || node.kind === 'rawgroup'" class="notice mt12">
            <Icon name="info" />
            <div class="grow small">{{ $t('device-graph.note.raw') }}</div>
          </div>
          <dl v-if="node.children.length" class="kv mt12">
            <dt>{{ $t('device-graph.children') }}</dt><dd>{{ node.children.length }}</dd>
            <dt>{{ $t('device-graph.descendants') }}</dt><dd>{{ node.size }}</dd>
          </dl>

          <template v-if="node.schema || node.api?.cards?.length">
            <div class="section-t">{{ $t('device-graph.kb') }}</div>
            <dl class="kv">
              <template v-if="node.schema">
                <dt>Schema</dt>
                <dd><router-link class="mono" :to="{ name: 'schema-edit', query: { node: node.schema } }">{{ node.schema }}</router-link></dd>
              </template>
              <template v-if="info?.semantic">
                <dt>{{ $t('device-graph.semantic') }}</dt><dd>{{ pickLang(info.semantic, locale) }}</dd>
              </template>
              <template v-if="info">
                <dt>{{ $t('device-graph.type') }}</dt><dd class="mono">{{ info.type }}</dd>
              </template>
              <template v-if="profile && (node.kind === 'attr' || node.kind === 'object')">
                <dt>Profile</dt>
                <dd><router-link class="mono" :to="{ name: 'profiles', query: { profile, node: node.schema ?? undefined } }">{{ profile }}</router-link></dd>
              </template>
              <template v-if="node.api?.cards?.length">
                <dt>{{ $t('device-graph.cards') }}</dt>
                <dd><div v-for="c in node.api.cards" :key="c" class="mono small">{{ c }}</div></dd>
              </template>
            </dl>
          </template>

          <template v-if="node.kind !== 'device'">
            <div class="section-t">{{ $t('device-graph.lines') }}</div>
            <div v-if="ranges.length" data-testid="line-chips">
              <button v-for="r in ranges" :key="r[0]" class="lnchip" type="button" @click="emit('line', r[0])">
                L{{ r[0] }}<template v-if="r[1] !== r[0]">–{{ r[1] }}</template>
              </button>
            </div>
            <span v-else class="small faint">{{ $t('device-graph.noLines') }}</span>
          </template>

          <template v-if="node.api">
            <div class="section-t">{{ $t('device-graph.deps') }} <span class="pill-count">{{ deps.out.length + deps.in.length }}</span></div>
            <p v-if="!deps.out.length && !deps.in.length" class="small faint">{{ $t('device-graph.noDeps') }}</p>
            <div v-else class="deps" data-testid="node-deps">
              <button v-for="(e, i) in deps.out" :key="`o${i}`" class="dep" type="button" @click="emit('pick', e.to)">
                <svg viewBox="0 0 26 10" width="26" height="10" :class="`ek ${EDGE_SHORT[e.kind]}`"><path class="ln" d="M1 5H22" /><path v-if="e.kind === 'mutex'" class="tee" d="M2 1v8M24 1v8" /><path v-else class="hd" d="M19 1.5L25 5l-6 3.5z" /></svg>
                <span><span class="dn">{{ nameOf(e.to) }}</span><span class="dt">{{ edgeName(e.kind) }}<template v-if="e.note"> · {{ e.note }}</template></span></span>
              </button>
              <button v-for="(e, i) in deps.in" :key="`i${i}`" class="dep" type="button" @click="emit('pick', e.from)">
                <svg viewBox="0 0 26 10" width="26" height="10" :class="`ek ${EDGE_SHORT[e.kind]}`"><path class="ln" d="M1 5H22" /><path v-if="e.kind === 'mutex'" class="tee" d="M2 1v8M24 1v8" /><path v-else class="hd" d="M19 1.5L25 5l-6 3.5z" /></svg>
                <span><span class="dn">← {{ nameOf(e.from) }}</span><span class="dt">{{ edgeName(e.kind) }}<template v-if="e.note"> · {{ e.note }}</template></span></span>
              </button>
            </div>
          </template>

          <div class="section-t">{{ $t('device-graph.nodeId') }}</div>
          <div class="tpl">{{ node.id }}</div>
        </template>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.p-detail { grid-area: detail; display: flex; flex-direction: column; overflow: hidden; }
.d-scroll { flex: 1; overflow: auto; padding: 14px; }
.d-name { font: 600 14px var(--font-mono); overflow-wrap: anywhere; }
.path { overflow-wrap: anywhere; }
.d-val { margin: 10px 0 12px; padding: 10px 12px; border-radius: 6px; background: var(--surface-2); border: 1px solid var(--line); }
.d-val .lbl { font-size: 11.5px; color: var(--ink-3); }
.d-val .v { font: 600 15px var(--font-mono); margin-top: 2px; overflow-wrap: anywhere; }
.d-val.dashed { border-style: dashed; background: transparent; }
.lnchip { font: 11.5px var(--font-mono); border: 1px solid var(--amber-line); background: var(--amber-soft); color: var(--amber-ink); border-radius: 4px; padding: 0 5px; cursor: pointer; margin: 0 4px 4px 0; display: inline-block; }
.deps { display: flex; flex-direction: column; gap: 4px; }
.dep { display: grid; grid-template-columns: 26px minmax(0, 1fr); gap: 8px; align-items: center; padding: 5px 6px; border-radius: 5px; cursor: pointer; border: 1px solid transparent; background: none; font: inherit; color: inherit; text-align: left; }
.dep:hover { background: var(--surface-2); border-color: var(--line); }
.dep > span { min-width: 0; display: flex; flex-direction: column; }
.dep .dn { font: 12px var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dep .dt { font-size: 11.5px; color: var(--ink-3); overflow-wrap: anywhere; }
.tpl { font: 12px/1.5 var(--font-mono); background: var(--surface-2); border: 1px solid var(--line); border-radius: 5px; padding: 6px 8px; overflow-wrap: anywhere; }
.ek .ln { stroke-width: 2; fill: none; }
.ek .tee { stroke-width: 2; }
.ek.ref .ln, .ek.ref .tee { stroke: var(--e-ref); } .ek.ref .hd { fill: var(--e-ref); }
.ek.pre .ln { stroke: var(--e-pre); } .ek.pre .hd { fill: var(--e-pre); }
.ek.side .ln { stroke: var(--e-side); stroke-dasharray: 2 3; } .ek.side .hd { fill: var(--e-side); }
.ek.mutex .ln, .ek.mutex .tee { stroke: var(--e-mutex); }
</style>
