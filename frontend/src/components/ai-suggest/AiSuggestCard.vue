<script setup lang="ts">
/** 一条 AI 建议（M8-2）：标题与类别、校验结果（实线小块）、正文（AI 文字紫色虚线，代码填入的实线）、依据与引用（可跳转，
 *  不存在的打删除线）、代码校验原因；采纳 / 编辑后采纳 / 忽略 / 恢复。被拒绝的灰底红虚线，不能采纳。 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import AiText from './AiText.vue'
import AiKbDetail from './AiKbDetail.vue'
import AiPreviewLines from './AiPreviewLines.vue'
import { CHANGE_CATEGORIES, adoptable, bodyText, previewLines, commandsOf, editContent, editText, levelOf, peerLine, refText, suspectOf, type RefInfo, type Suggestion } from './logic'

const props = defineProps<{ item: Suggestion; open: boolean; canWrite: boolean; canKb: boolean; busy?: boolean }>()
const emit = defineEmits<{
  toggle: []
  adopt: [content?: Record<string, unknown>]
  dismiss: []
  restore: []
  jump: [ref: RefInfo]
}>()
const { t, te } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`ai-suggest.${k}`, p ?? {})

const it = computed(() => props.item)
const fail = computed(() => it.value.check_status === 'reject')
const adopted = computed(() => it.value.status === 'adopted')
const c = computed(() => (it.value.content ?? {}) as Record<string, unknown>)
const VI: Record<string, string> = { pass: 'ok', warn: 'warn', reject: 'err' }
const vchip = computed(() => (fail.value ? 'fail' : it.value.check_status))
const blockedKb = computed(() => it.value.kb && !props.canKb)
// 报告摘要一次给出中英两段（kind 为段落语言），AI 写的标题语言不定；标题按界面语言取文案（REQ-056-06）
const title = computed(() => {
  const para = it.value.skill === 'report-summary' ? `reportPara.${it.value.kind === 'zh-CN' ? 'zh' : it.value.kind}` : ''
  return para && te(`ai-suggest.${para}`) ? T(para) : it.value.check.title_display || it.value.title || `#${it.value.id}`
})

function reasonText(code: string): string {
  return te(`ai-suggest.r.${code}`) ? T(`r.${code}`) : code
}
const hintLine = computed(() => {
  const key = String(c.value.key ?? '')
  const val = String(c.value.value ?? '')
  const target = it.value.refs.find((r) => r.id === c.value.target)
  const keyT = te(`ai-suggest.key.${key}`) ? T(`key.${key}`) : key
  const valT = key === 'role' && te(`ai-suggest.role.${val.toLowerCase()}`) ? T(`role.${val.toLowerCase()}`) : val
  return { target: target?.label ?? String(c.value.target ?? ''), key: keyT, value: valT }
})
const scriptRes = computed(() => it.value.check.result?.result ?? null)
// M8-3：正文（text_only / refs_exist 的 text，脚本的 explain）、风险或优先级、更可能出错的一端、推测对端、命令写法
const body = computed(() => bodyText(it.value))
const level = computed(() => levelOf(it.value))
const suspect = computed(() => suspectOf(it.value))
const peer = computed(() => peerLine(it.value))
const cmds = computed(() => commandsOf(it.value))
// M8-4：变更与割接组由代码给出的预览行，以及说明 / 理由文字（AI 文字，对象名由代码填入）
const preview = computed(() => (CHANGE_CATEGORIES.has(it.value.category) ? previewLines(it.value) : []))
const explain = computed(() => (CHANGE_CATEGORIES.has(it.value.category) ? it.value.check.display ?? '' : ''))

// ---------- 编辑后采纳 ----------
const editing = ref(false)
const draft = ref('')
const editErr = ref('')
function startEdit(): void {
  draft.value = editText(it.value)
  editErr.value = ''
  editing.value = true
}
function submitEdit(): void {
  const content = editContent(it.value, draft.value)
  if (!content) { editErr.value = T('badJson'); return }
  emit('adopt', content)
}
defineExpose({ stopEdit: () => { editing.value = false }, setEditError: (m: string) => { editErr.value = m } })
</script>

<template>
  <article
    class="sg"
    :class="{ 'is-open': open, 'is-fail': fail, 'is-adopted': adopted, 'is-dismissed': it.status === 'dismissed' }"
    :data-testid="`ai-sg-${it.id}`"
    :data-check="it.check_status"
    :data-status="it.status"
  >
    <div class="sg-h" @click="emit('toggle')">
      <button class="tw" type="button" :aria-expanded="open" :aria-label="it.title"><Icon name="chevR" small /></button>
      <div class="sg-t">
        <div class="tl"><span class="cat">{{ te(`ai-suggest.cat.${it.category}`) ? T(`cat.${it.category}`) : it.category }}</span><span>{{ title }}</span></div>
        <div class="rt">
          <span v-if="adopted" class="adopted-chip"><Icon name="spark" small />{{ it.edited ? T('editedChip') : T('adoptedChip') }}</span>
          <span v-else-if="it.status === 'dismissed'" class="tag">{{ T('dismissedTag') }}</span>
          <template v-else>
            <span class="vchip" :class="vchip"><Icon :name="VI[it.check_status]" small />{{ T(`v.${it.check_status}`) }}</span>
            <span v-if="it.status === 'reverted'" class="tag">{{ T('revertedTag') }}</span>
          </template>
        </div>
      </div>
    </div>

    <div v-if="open" class="sg-b">
      <template v-if="!editing">
        <div v-if="level || suspect" class="lvrow">
          <span v-if="level" class="risk" :class="level.cls" data-testid="ai-sg-level">{{ T(`${level.k}.${level.v}`) }}</span>
          <span v-if="suspect" class="small" data-testid="ai-sg-suspect">{{ T('suspect', { d: suspect }) }}</span>
        </div>
        <AiText v-if="body && it.category !== 'script_valid'" :segments="it.check.segments" :text="body" :refs="it.refs" :adopted="adopted" @jump="emit('jump', $event)" />
        <div v-if="cmds.length" class="body" data-testid="ai-sg-commands">
          <h4>{{ T('commands') }}</h4>
          <div v-for="(x, i) in cmds" :key="i" class="cmdrow"><span class="cv">{{ x.card }}</span><code class="mono">{{ x.text }}</code></div>
        </div>
        <div v-if="peer" class="body" data-testid="ai-sg-peer">
          <div><b class="mono">{{ peer.a }}</b> ⟷ <b class="mono hintv">{{ peer.b }}</b><span v-if="peer.external" class="small faint"> · {{ T('external') }}</span></div>
          <AiText v-if="c.reason" inline :segments="it.check.segments" :text="String(c.reason)" :refs="it.refs" :adopted="adopted" @jump="emit('jump', $event)" />
        </div>
        <div v-else-if="it.category === 'view_hint'" class="body">
          <div><b>{{ hintLine.key }}</b> · {{ hintLine.target }} → <b class="hintv">{{ hintLine.value }}</b></div>
          <AiText v-if="c.reason" inline :segments="it.check.segments" :text="String(c.reason)" :refs="it.refs" :adopted="adopted" @jump="emit('jump', $event)" />
        </div>
        <template v-else-if="it.category === 'script_valid'">
          <AiText v-if="body" inline :segments="null" :text="body" :refs="it.refs" :adopted="adopted" />
          <pre class="code-pre mono" data-testid="ai-sg-script">{{ String(c.script ?? '') }}</pre>
          <div v-if="scriptRes" class="small faint">{{ T('scriptRes', { a: scriptRes.lines_added ?? 0, d: scriptRes.lines_removed ?? 0, o: scriptRes.lines_overridden ?? 0 }) }}</div>
        </template>
        <AiKbDetail v-else-if="it.category === 'kb_review' || it.category === 'sanitize_rule'" :item="it" />
        <AiText v-if="explain" inline :segments="it.check.segments" :text="explain" :refs="it.refs" :adopted="adopted" @jump="emit('jump', $event)" />
        <AiPreviewLines v-if="preview.length" :lines="preview" />
      </template>
      <div v-else class="editbox" data-testid="ai-sg-editbox">
        <label class="small faint">{{ T('editHint') }}</label>
        <textarea v-model="draft" class="textarea" :class="{ mono: it.category !== 'text_only' }" rows="6" data-testid="ai-sg-edit-text" />
        <div v-if="editErr" class="small" style="color: var(--red-ink)" data-testid="ai-sg-edit-error">{{ editErr }}</div>
        <div class="row2">
          <button class="btn btn-sm btn-ai" type="button" :disabled="busy" data-testid="ai-sg-edit-submit" @click="submitEdit"><Icon name="check" small />{{ T('checkAdopt') }}</button>
          <button class="btn btn-sm btn-ghost" type="button" @click="editing = false">{{ T('cancelEdit') }}</button>
        </div>
      </div>

      <div v-if="it.refs.length">
        <h4>{{ T('refs') }}</h4>
        <div class="refs">
          <button
            v-for="(r, i) in it.refs"
            :key="i"
            type="button"
            class="aref"
            :class="{ bad: !r.found }"
            :title="r.found ? (r.node ?? r.type ?? '') : reasonText('ref_not_found')"
            data-testid="ai-sg-ref"
            @click="r.found && emit('jump', r)"
          ><Icon :name="r.type === 'device' ? 'server' : 'graph'" small />{{ refText(r) }}</button>
        </div>
      </div>

      <div class="vf" :class="vchip" data-testid="ai-sg-check">
        <Icon :name="VI[it.check_status]" />
        <div>
          <b>{{ T(`v.${it.check_status}`) }}</b>
          <ul v-if="it.check.reasons && it.check.reasons.length">
            <li v-for="(r, i) in it.check.reasons" :key="i">{{ reasonText(r.code) }}<template v-if="r.ref || r.detail">：<span class="mono">{{ r.ref ?? r.detail }}</span></template></li>
          </ul>
        </div>
      </div>
    </div>

    <div class="sg-f">
      <template v-if="editing" />
      <template v-else-if="it.status !== 'adopted' && it.status !== 'dismissed'">
        <template v-if="fail">
          <span class="why-no"><Icon name="lock" small />{{ T('cantAdopt') }}</span>
          <button v-if="!open" class="btn btn-xs btn-ghost" type="button" @click="emit('toggle')">{{ T('seeWhy') }}</button>
          <span class="grow" />
          <button v-if="canWrite && it.status === 'pending'" class="btn btn-xs btn-ghost" type="button" data-testid="ai-sg-dismiss" @click="emit('dismiss')">{{ T('dismiss') }}</button>
        </template>
        <template v-else-if="canWrite && !blockedKb">
          <button class="btn btn-xs btn-ai" type="button" :disabled="busy || !adoptable(it)" data-testid="ai-sg-adopt" @click="emit('adopt')"><Icon name="check" small />{{ T('adopt') }}</button>
          <button class="btn btn-xs btn-aio" type="button" :disabled="busy" data-testid="ai-sg-edit" @click="startEdit"><Icon name="pencil" small />{{ T('editAdopt') }}</button>
          <button v-if="it.status === 'pending'" class="btn btn-xs btn-ghost" type="button" :disabled="busy" data-testid="ai-sg-dismiss" @click="emit('dismiss')">{{ T('dismiss') }}</button>
        </template>
        <span v-else class="small faint">{{ blockedKb ? T('kbOnly') : T('readOnly') }}</span>
      </template>
      <template v-else-if="it.status === 'dismissed'">
        <button v-if="canWrite" class="btn btn-xs btn-ghost" type="button" data-testid="ai-sg-restore" @click="emit('restore')"><Icon name="rollback" small />{{ T('restore') }}</button>
      </template>
      <span v-else class="small faint">{{ T('undoBelow') }}</span>
    </div>
  </article>
</template>

<style scoped>
.code-pre { margin: 0; padding: 8px 10px; border: 1px solid var(--line); border-radius: 5px; background: var(--surface); max-height: 220px; overflow: auto; font-size: 12px; white-space: pre; }
.hintv { color: var(--ai); }
.sg-h .tw { pointer-events: none; }
.lvrow { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.risk { font-size: 11px; font-weight: 600; border-radius: 3px; padding: 0 5px; line-height: 17px; display: inline-flex; }
.risk.hi { color: var(--red-ink); background: var(--red-soft); }
.risk.mid { color: var(--amber-ink); background: var(--amber-soft); }
.risk.lo { color: var(--teal-ink); background: var(--teal-soft); }
.cmdrow { display: flex; gap: 8px; align-items: baseline; margin-top: 4px; min-width: 0; }
.cmdrow code { font-size: 12px; overflow-wrap: anywhere; }
</style>
