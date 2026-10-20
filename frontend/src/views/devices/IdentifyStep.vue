<script setup lang="ts">
/**
 * 导入对话框的“识别与 Profile”一步（REQ-044，预览 DevelopDocs/ui-preview/REQ-044/import.html）：
 * 每个文件的识别结果、匹配程度与来源；Profile 下拉列出试解析的候选（百分比 = 识别出的命令行比例，带“推荐”）；
 * 展开行看候选的比例条、型号规则命中、“记住”（范围、设备名模式、版本、特征命令，并提示本批会命中的文件）；
 * 认不出厂商：只存原文 / 在全部 Profile 中选 / 跳过。选择保存在父组件传入的 choices 里（按来源名）。
 */
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import VendorBadge from '@/components/vendor-badge.vue'
import { vendorLabel } from './logic'
import { batchHits, hasCondition, levelCounts, options, pct, regexOk, unknownHigh, type FileChoice, type InspectFile } from './model'

const props = defineProps<{ files: InspectFile[]; choices: Record<string, FileChoice>; canGlobal: boolean }>()
const open = ref<Set<string>>(new Set(props.files.filter((f) => f.ok && f.match_level !== 'exact').slice(0, 1).map((f) => f.source)))
const counts = computed(() => levelCounts(props.files))

function toggle(src: string): void {
  const s = new Set(open.value)
  if (s.has(src)) s.delete(src)
  else s.add(src)
  open.value = s
}
function useRecommended(): void {
  for (const f of props.files) {
    const c = props.choices[f.source]
    if (c && f.vendor && f.recommended) c.profile = f.recommended
  }
}
function hits(f: InspectFile, c: FileChoice): string[] {
  return batchHits(props.files, c.rule, f.vendor ?? '')
}
const short = (s: string) => s.split('/').pop() ?? s
/** 当前选中的候选（未识别行数与比例）。 */
function chosen(f: InspectFile): { unknown: number; unknownRatio: number } | null {
  const c = f.candidates?.find((x) => x.profile === props.choices[f.source]?.profile)
  return c ? { unknown: c.unknown, unknownRatio: c.unknown / Math.max(1, c.command + c.unknown) } : null
}
</script>

<template>
  <div data-testid="import-identify">
    <div class="notice info"><Icon name="info" /><div class="grow small">{{ $t('model.idNote') }}</div></div>
    <div class="row mt12" style="gap: 8px">
      <span class="mt-chip exact">{{ $t('model.level.exact') }} {{ counts.exact }}</span>
      <span class="mt-chip approx">{{ $t('model.level.approx') }} {{ counts.approx }}</span>
      <span class="mt-chip none">{{ $t('model.level.none') }} {{ counts.none }}</span>
      <span class="grow" />
      <button class="btn btn-sm" type="button" data-testid="use-recommended" @click="useRecommended"><Icon name="check" small />{{ $t('model.useRecommended') }}</button>
    </div>
    <div class="tbl-wrap mt12" style="max-height: 460px">
      <table class="tbl idt" data-testid="identify-table">
        <thead>
          <tr>
            <th style="width: 28px" />
            <th>{{ $t('devices.colFile') }}</th>
            <th>{{ $t('devices.colDetected') }}</th>
            <th>{{ $t('model.colMatch') }}</th>
            <th>Profile</th>
            <th class="num">{{ $t('devices.colUnknown') }}</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="f in files" :key="f.source">
            <tr v-if="!f.ok" class="failed">
              <td />
              <td class="mono">{{ f.source }}</td>
              <td colspan="4"><span class="tag fail">{{ $t('c.failed') }}</span> <span class="small">{{ f.error }}</span></td>
            </tr>
            <template v-else-if="choices[f.source]">
              <tr :class="{ expanded: open.has(f.source) }" :data-testid="`identify-row-${short(f.source)}`">
                <td><button class="btn btn-ghost btn-icon btn-xs" type="button" :aria-expanded="open.has(f.source)" :aria-label="f.source" @click="toggle(f.source)"><Icon :name="open.has(f.source) ? 'chevD' : 'chevR'" small /></button></td>
                <td>
                  <div class="fname">{{ f.source }}</div>
                  <div class="sub">{{ $t('devices.deviceName') }} <span class="mono">{{ f.device }}</span> · {{ f.lines }}</div>
                </td>
                <td class="nowrap">
                  <VendorBadge v-if="f.vendor" :of="f.vendor">{{ vendorLabel(f.vendor) }}</VendorBadge>
                  <span v-else class="tag warn">{{ $t('devices.vendorUnknown') }}</span>
                  <div class="sub mono">{{ f.version || $t('devices.noVersion') }}</div>
                </td>
                <td class="nowrap">
                  <span class="mt-chip" :class="f.match_level">{{ $t(`model.level.${f.match_level}`) }}</span>
                  <div class="sub"><span class="src-chip" :class="f.profile_source">{{ $t(`model.src.${f.profile_source}`) }}<template v-if="f.rule"> #{{ f.rule.id }}</template></span></div>
                </td>
                <td>
                  <span v-if="!f.vendor && choices[f.source].unknown !== 'pick'" class="faint small">{{ $t(choices[f.source].unknown === 'raw' ? 'model.rawOnly' : 'model.skipped') }}</span>
                  <select v-else v-model="choices[f.source].profile" class="select psel mono" :data-testid="`identify-profile-${short(f.source)}`">
                    <option v-if="!f.vendor" value="">{{ $t('model.pickProfile') }}</option>
                    <option v-for="o in options(f)" :key="o.profile" :value="o.profile">{{ o.profile }}{{ o.ratio !== null ? ` · ${pct(o.ratio)}` : '' }}{{ o.recommended ? ` · ${$t('model.recommended')}` : '' }}</option>
                  </select>
                  <div v-if="choices[f.source].remember && hasCondition(choices[f.source].rule)" class="sub" style="color: var(--teal-ink)"><Icon name="rules" small /> {{ $t('model.willRemember', { scope: $t(`model.scope.${choices[f.source].scope}`) }) }}</div>
                </td>
                <td class="num"><span class="unk-r" :class="{ hi: unknownHigh(chosen(f)?.unknownRatio) }">{{ chosen(f)?.unknown ?? '—' }}</span></td>
              </tr>
              <tr v-if="open.has(f.source)" class="detail">
                <td />
                <td colspan="5">
                  <template v-if="!f.vendor">
                    <div class="notice warn"><Icon name="warn" /><div class="grow small">{{ $t('model.unknownVendor') }}</div></div>
                    <div class="uv-opts mt8" role="radiogroup">
                      <label v-for="a in (['raw', 'pick', 'skip'] as const)" :key="a"><input v-model="choices[f.source].unknown" type="radio" :value="a" :data-testid="`identify-uv-${a}-${short(f.source)}`"><span>{{ $t(`model.uv.${a}`) }}</span></label>
                    </div>
                  </template>
                  <template v-if="f.vendor || choices[f.source].unknown === 'pick'">
                    <div class="small faint mt8" style="margin-bottom: 4px">{{ f.vendor ? $t('model.trialHint') : $t('model.allHint') }}</div>
                    <div v-if="f.candidates?.length" class="cands" role="radiogroup">
                      <label v-for="c in f.candidates" :key="c.profile" class="cand" :class="{ on: c.profile === choices[f.source].profile }">
                        <input v-model="choices[f.source].profile" type="radio" :value="c.profile">
                        <span>
                          <span class="pid">{{ c.profile }}</span><span v-if="f.vendor && c.profile === f.recommended" class="rec-mark">{{ $t('model.recommended') }}</span>
                          <div class="meta">{{ c.title }} · command {{ c.command }} · unknown {{ c.unknown }}<template v-if="c.exact"> · {{ $t('model.src.auto') }}</template><template v-else-if="c.fallback"> · {{ $t('model.src.fallback') }}</template></div>
                        </span>
                        <span class="bar"><i :style="{ width: `${(c.ratio * 100).toFixed(1)}%` }" /></span>
                        <span class="pct">{{ pct(c.ratio) }}</span>
                      </label>
                    </div>
                    <p v-else class="faint small">{{ $t('model.noCand') }}</p>
                    <div v-if="f.rule" class="notice info mt8"><Icon name="rules" /><div class="grow small">{{ $t('model.ruleHit', { id: f.rule.id, c: [f.rule.name_pattern, f.rule.version, f.rule.feature].filter(Boolean).join(' · '), p: f.rule.profile, scope: $t(`model.scope.${f.rule.scope}`) }) }}</div></div>
                    <div v-if="f.previous" class="small faint mt8">{{ $t('model.previous', { p: f.previous.profile || '—', s: $t(`model.src.${f.previous.source}`) }) }}</div>
                    <div v-if="choices[f.source].profile" class="remember">
                      <label class="row" style="gap: 6px">
                        <input v-model="choices[f.source].remember" type="checkbox" :data-testid="`identify-remember-${short(f.source)}`">
                        <b>{{ $t('model.remember') }}</b><span class="faint small">{{ $t('model.rememberHint') }}</span>
                      </label>
                      <template v-if="choices[f.source].remember">
                        <div class="grid">
                          <label class="f">{{ $t('model.fScope') }}
                            <select v-model="choices[f.source].scope" class="select">
                              <option value="project">{{ $t('model.scope.project') }}</option>
                              <option value="global" :disabled="!canGlobal">{{ canGlobal ? $t('model.scope.global') : $t('model.globalOnly') }}</option>
                            </select>
                          </label>
                          <label class="f">{{ $t('model.fName') }}<input v-model="choices[f.source].rule.name_pattern" class="input mono"></label>
                          <label class="f">{{ $t('model.fVersion') }}<input v-model="choices[f.source].rule.version" class="input mono" :class="{ bad: !regexOk(choices[f.source].rule.version) }"></label>
                          <label class="f" style="grid-column: 1 / -1">{{ $t('model.fFeature') }}<input v-model="choices[f.source].rule.feature" class="input mono" placeholder="^set neid" :class="{ bad: !regexOk(choices[f.source].rule.feature) }"></label>
                        </div>
                        <div v-if="!hasCondition(choices[f.source].rule)" class="hit warn">{{ $t('model.needCond') }}</div>
                        <div v-else-if="!regexOk(choices[f.source].rule.version) || !regexOk(choices[f.source].rule.feature)" class="hit warn">{{ $t('model.badRegex') }}</div>
                        <div v-else-if="f.vendor" class="hit"><Icon name="check" small /> {{ $t('model.batchHits', { n: hits(f, choices[f.source]).length, f: hits(f, choices[f.source]).map(short).join(', ') }) }}</div>
                      </template>
                    </div>
                  </template>
                </td>
              </tr>
            </template>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.idt td { vertical-align: top; }
.idt td.nowrap { white-space: nowrap; }
.idt .fname { font: 12px var(--font-mono); }
.idt .sub { font-size: 11.5px; color: var(--ink-3); margin-top: 2px; }
.idt tr.expanded td { background: var(--surface-2); }
.idt tr.detail td { background: var(--surface-2); border-top: 0; padding-top: 0; }
.idt tr.failed td { background: color-mix(in srgb, var(--red-soft) 55%, transparent); }
.idt .psel { min-width: 260px; max-width: 100%; }
.mt-chip { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; font-weight: 600; padding: 1px 8px 1px 6px; border-radius: 999px; border: 1px solid var(--line-strong); white-space: nowrap; }
.mt-chip::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.mt-chip.exact { color: var(--teal-ink); background: var(--teal-soft); border-color: var(--teal-line); }
.mt-chip.approx { color: var(--amber-ink); background: var(--amber-soft); border-color: var(--amber-line); }
.mt-chip.none { color: var(--red-ink); background: var(--red-soft); border-color: var(--red-line); }
.src-chip { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; padding: 0 6px; border-radius: 3px; border: 1px dashed var(--line-strong); color: var(--ink-2); white-space: nowrap; }
.src-chip.fallback, .src-chip.manual, .src-chip.rule { border-style: solid; border-color: var(--amber-line); color: var(--amber-ink); background: var(--amber-soft); }
.src-chip.none { border-style: solid; border-color: var(--red-line); color: var(--red-ink); background: var(--red-soft); }
.unk-r { font: 12px var(--font-mono); color: var(--ink-3); }
.unk-r.hi { color: var(--red-ink); font-weight: 600; }
.cands { display: flex; flex-direction: column; gap: 2px; border: 1px solid var(--line); border-radius: 8px; padding: 4px; background: var(--surface); }
.cand { display: grid; grid-template-columns: 18px minmax(0, 1fr) 120px 56px; gap: 8px; align-items: center; padding: 6px 8px; border-radius: 6px; cursor: pointer; }
.cand:hover { background: var(--surface-3); }
.cand.on { background: var(--teal-soft); }
.cand .pid { font: 12px var(--font-mono); }
.cand .meta { font-size: 11px; color: var(--ink-3); }
.cand .bar { height: 6px; border-radius: 3px; background: var(--surface-3); overflow: hidden; }
.cand .bar i { display: block; height: 100%; background: var(--teal); }
.cand .pct { font: 600 12px var(--font-mono); text-align: right; }
.rec-mark { font-size: 10.5px; font-weight: 700; color: var(--teal-ink); border: 1px solid var(--teal-line); background: var(--teal-soft); border-radius: 3px; padding: 0 4px; margin-left: 6px; }
.remember { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; background: var(--surface); margin-top: 8px; }
.remember .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px 12px; margin-top: 8px; }
.remember label.f { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--ink-2); }
.remember .hit { font-size: 12px; color: var(--teal-ink); margin-top: 6px; }
.remember .hit.warn { color: var(--amber-ink); }
.input.bad { border-color: var(--red-line); }
.uv-opts { display: flex; flex-direction: column; gap: 6px; }
.uv-opts label { display: flex; gap: 6px; align-items: flex-start; font-size: 12.5px; }
@media (max-width: 1100px) { .remember .grid { grid-template-columns: 1fr; } .idt .psel { min-width: 0; } }
</style>
