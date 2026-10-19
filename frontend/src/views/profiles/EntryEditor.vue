<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { del, errorText, put } from '@/api'
import Icon from '@/components/Icon.vue'
import { pickLang } from '@/i18n'
import { entryBody, entryOrigin, formDirty, formFromEntry, type EntryForm } from './entries'
import { formatDefault, parseDefault } from './format'
import type { Entry } from './types'
import StyleForms from '../schema/StyleForms.vue'
import { useAuth } from '@/stores/auth'
import KbSuggest from '@/components/kb-suggest.vue'

const props = defineProps<{
  profileId: string
  entry: Entry
  parentId: string | null
  parentEntries: Map<string, Entry>
  showRules: string[]
}>()
const emit = defineEmits<{ changed: [message: string] }>()
const { t, locale } = useI18n()
// 普通用户只读（REQ-036）：不能覆盖、删除或保存条目，可以对默认值提建议
const auth = useAuth()
const suggesting = ref(false)
const suggested = ref(false)

const VERIFIED = ['doc', 'roundtrip', 'device']
const origin = computed(() => entryOrigin(props.entry, props.parentEntries))
const parentEntry = computed(() => props.parentEntries.get(props.entry.node))
/** 继承或未填写的条目，点“在本 Profile 覆盖 / 填写”后才可编辑 */
const opened = ref(false)
const editable = computed(() => auth.isKbEditor && (origin.value === 'own' || origin.value === 'override' || opened.value))
const base = ref<EntryForm>(formFromEntry(props.entry))
const form = ref<EntryForm>({ ...base.value })
const busy = ref(false)
const err = ref('')
const confirmDel = ref(false)

function reset() {
  base.value = formFromEntry(props.entry.state === 'unfilled' ? undefined : props.entry)
  form.value = { ...base.value }
  opened.value = false
  err.value = ''
  confirmDel.value = false
}
watch(() => [props.profileId, props.entry], reset, { immediate: true })

const dirty = computed(() => opened.value || formDirty(form.value, base.value))
const rules = computed(() => (props.showRules.length ? props.showRules : ['always', 'hide_when_default', 'never']))
const cards = computed(() => props.entry.cards ?? [])
const enc = encodeURIComponent
const path = computed(() => `/kb/profiles/${enc(props.profileId)}/entries/${enc(props.entry.node)}`)

async function save() {
  busy.value = true
  err.value = ''
  try {
    await put(path.value, entryBody(form.value, (s) => parseDefault(s, props.entry.default)))
    emit('changed', t('profiles.savedDraft'))
  } catch (e) {
    err.value = detailText(e)
  } finally {
    busy.value = false
  }
}

async function remove() {
  if (!confirmDel.value) { confirmDel.value = true; return }
  busy.value = true
  err.value = ''
  try {
    await del(path.value)
    emit('changed', origin.value === 'override' ? t('profiles.restored') : t('profiles.deleted'))
  } catch (e) {
    err.value = detailText(e)
  } finally {
    busy.value = false
    confirmDel.value = false
  }
}

function detailText(e: unknown): string {
  const data = (e as { data?: unknown }).data
  return Array.isArray(data) && data.length ? `${errorText(e)}：${data.join('；')}` : errorText(e)
}
</script>

<template>
  <aside class="panel editor" data-testid="entry-editor">
    <div class="panel-h">
      <h2 class="mono" style="font-size:13.5px">{{ entry.node }}</h2>
      <router-link class="small" :to="{ name: 'schema-edit', query: { node: entry.node } }">{{ $t('profiles.schemaDef') }}</router-link>
    </div>
    <div class="panel-b">
      <div class="small muted">{{ pickLang(entry.semantic, String(locale)) }} <span class="mono faint">· {{ entry.type }}</span></div>
      <StyleForms :id="entry.node" :type="entry.type" />

      <div class="inh-box" data-testid="entry-origin">
        <div class="row">
          <span class="small" v-if="origin === 'override'">
            <span class="tag inherited">{{ $t('profiles.overridden') }}</span>
            {{ $t('profiles.inhValueFrom') }} <span class="mono">{{ parentEntry?.origin || parentId }}</span>
          </span>
          <span class="small" v-else-if="origin === 'own'">
            <span class="tag explicit">{{ $t('profiles.ownEntry') }}</span>
            {{ parentId ? $t('profiles.ownNotInParent') : $t('profiles.ownRoot') }}
          </span>
          <span class="small" v-else-if="origin === 'inherited'">
            <span class="tag inherited">{{ $t('src.inherited') }}</span>
            {{ $t('profiles.valuesFrom') }} <span class="mono">{{ entry.origin }}</span>
          </span>
          <span class="small" v-else><span class="tag unfilled">{{ $t('st.unfilled') }}</span> {{ $t('profiles.unfilledHint') }}</span>

          <button v-if="!auth.isKbEditor" class="btn btn-xs" data-testid="entry-suggest" @click="suggesting = true; suggested = false">
            <Icon name="chat" small />{{ $t('kbsugg.button') }}
          </button>
          <button v-else-if="origin === 'override'" class="btn btn-xs" :disabled="busy" data-testid="entry-restore" @click="remove">
            <Icon name="rollback" small />{{ confirmDel ? $t('profiles.confirmRestore') : $t('profiles.restore') }}
          </button>
          <button v-else-if="origin === 'own'" class="btn btn-xs btn-danger" :disabled="busy" data-testid="entry-delete" @click="remove">
            <Icon name="trash" small />{{ confirmDel ? $t('profiles.confirmDelete') : $t('profiles.deleteEntry') }}
          </button>
          <button v-else-if="!opened" class="btn btn-xs" data-testid="entry-override" @click="opened = true">
            {{ origin === 'inherited' ? $t('profiles.overrideHere') : $t('profiles.fillHere') }}
          </button>
        </div>
        <div v-if="origin === 'override' && parentEntry" class="small muted mt8 mono">
          {{ parentEntry.state === 'supported' ? $t('st.supported') : $t('st.unsupported') }}
          · {{ $t('profiles.default') }} {{ formatDefault(parentEntry.default) || '—' }} · {{ parentEntry.show_rule }}
        </div>
        <div v-if="opened && origin === 'inherited'" class="small muted mt8">{{ $t('profiles.overrideNote') }}</div>
      </div>

      <div class="row" style="justify-content:space-between">
        <span class="field-label">{{ $t('profiles.supported') }}</span>
        <label class="switch"><input v-model="form.supported" type="checkbox" :disabled="!editable" data-testid="entry-supported"><span></span></label>
      </div>

      <div class="field">
        <label>{{ $t('profiles.defaultValue') }}</label>
        <input v-model="form.default" class="input mono" :readonly="!editable" :disabled="!form.supported"
               :placeholder="$t('profiles.defaultPh')" data-testid="entry-default">
        <div class="hint">{{ $t('profiles.defaultHint') }}</div>
      </div>

      <div class="field">
        <label>{{ $t('profiles.showRule') }}</label>
        <select v-model="form.show_rule" class="select mono" :disabled="!editable" data-testid="entry-show-rule">
          <option v-for="r in rules" :key="r" :value="r">{{ r }}</option>
        </select>
        <div class="hint">{{ $t('profiles.showRuleHint') }}</div>
      </div>

      <div class="form-grid">
        <div class="field span2">
          <label>{{ $t('profiles.source') }}</label>
          <input v-model="form.source" class="input" :readonly="!editable" data-testid="entry-source">
        </div>
        <div class="field">
          <label>{{ $t('profiles.verifiedBy') }}</label>
          <select v-model="form.verified" class="select" :disabled="!editable" data-testid="entry-verified">
            <option v-for="v in VERIFIED" :key="v" :value="v">{{ v }}</option>
          </select>
        </div>
        <div class="field">
          <label>{{ $t('profiles.credibility') }}</label>
          <div class="cred-ro">
            <span v-if="entry.credibility" :class="['tag', entry.credibility]">{{ entry.credibility }}</span>
            <span v-else class="faint">—</span>
            <span v-if="entry.manual" class="tag t-violet">{{ $t('profiles.manual') }}</span>
          </div>
        </div>
      </div>
      <div class="hint small faint">{{ $t('profiles.credHint') }}</div>

      <div v-if="cards.length" class="field">
        <label>{{ $t('profiles.cards', { n: cards.length }) }}</label>
        <div class="cards">
          <span v-for="c in cards" :key="c" class="tag mono">{{ c }}</span>
        </div>
      </div>

      <div v-if="suggested" class="notice ok" data-testid="entry-suggested"><Icon name="check" /><div class="grow small">{{ $t('kbsugg.submitted') }}</div></div>
      <KbSuggest v-if="suggesting" :target="`${profileId}:${entry.node}`" :current="formatDefault(entry.default)" kind="default" @close="suggesting = false" @submitted="suggesting = false; suggested = true" />
      <div v-if="err" class="notice err" data-testid="entry-error"><Icon name="err" /><div class="grow small">{{ err }}</div></div>
    </div>
    <div v-if="editable" class="panel-f">
      <span class="small faint">{{ $t('profiles.saveNote') }}</span>
      <span style="flex:1"></span>
      <button class="btn btn-sm" :disabled="busy" @click="reset">{{ $t('c.cancel') }}</button>
      <button class="btn btn-sm btn-primary" :disabled="busy || !dirty" data-testid="entry-save" @click="save">{{ busy ? $t('c.loading') : $t('profiles.saveDraft') }}</button>
    </div>
  </aside>
</template>

<style scoped>
.editor .panel-b { display: flex; flex-direction: column; gap: 14px; }
.editor .panel-f { display: flex; align-items: center; gap: 8px; }
.inh-box { border: 1px dashed var(--teal-line); border-radius: 6px; padding: 9px 11px; background: color-mix(in srgb, var(--teal-soft) 45%, transparent); }
.inh-box .row { justify-content: space-between; gap: 8px; }
.cred-ro { display: flex; gap: 6px; align-items: center; min-height: 32px; }
.cards { display: flex; flex-wrap: wrap; gap: 4px; max-height: 120px; overflow: auto; }
</style>
