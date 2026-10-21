<script setup lang="ts">
/**
 * 发现项目（M9-8，REQ-050，预览 DevelopDocs/ui-preview/M9-8/discover.html）：属主设为“可被搜索”的项目，
 * 只显示名称、简介、属主、设备数；申请加入（角色默认只读、理由），申请中可撤回。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import ProjRole from '@/components/proj-role.vue'
import { errorText } from '@/api'
import { useAuth } from '@/stores/auth'
import { cancelRequest, discover, requestJoin, splitMatch, type DiscoverRow } from './join/join'

const { t } = useI18n()
const route = useRoute()
const auth = useAuth()
const rows = ref<DiscoverRow[]>([])
const loading = ref(true)
const loadError = ref('')
const q = ref(typeof route.query.q === 'string' ? route.query.q : '')
const toast = ref('')
const ro = computed(() => !!auth.me?.read_only)

const shown = computed(() => {
  const needle = q.value.trim().toLowerCase()
  if (!needle) return rows.value
  return rows.value.filter((r) => [r.name, r.description, r.owner ?? '', r.ref].join(' ').toLowerCase().includes(needle))
})
const hl = (text: string) => splitMatch(text, q.value.trim())

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    rows.value = (await discover()).projects
  } catch (e) {
    loadError.value = errorText(e)
  } finally {
    loading.value = false
  }
}
function flash(msg: string): void {
  toast.value = msg
  setTimeout(() => { if (toast.value === msg) toast.value = '' }, 3200)
}

/* 申请对话框 */
const cur = ref<DiscoverRow | null>(null)
const role = ref<'read' | 'edit'>('read')
const reason = ref('')
const busy = ref(false)
const dlgErr = ref('')
function ask(r: DiscoverRow): void {
  cur.value = r
  role.value = 'read'
  reason.value = ''
  dlgErr.value = ''
}
async function send(): Promise<void> {
  if (!cur.value) return
  busy.value = true
  dlgErr.value = ''
  try {
    await requestJoin(cur.value.id, role.value, reason.value.trim())
    flash(t('join.requestSent', { p: cur.value.name }))
    cur.value = null
    await load()
  } catch (e) {
    dlgErr.value = errorText(e)
  } finally {
    busy.value = false
  }
}
async function cancel(r: DiscoverRow): Promise<void> {
  if (!r.request_id) return
  try {
    await cancelRequest(r.request_id)
    flash(t('join.cancelled'))
    await load()
  } catch (e) {
    loadError.value = errorText(e)
  }
}
function onKey(e: KeyboardEvent): void { if (e.key === 'Escape') cur.value = null }
onMounted(() => { void load(); document.addEventListener('keydown', onKey) })
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
watch(() => route.query.q, (v) => { if (typeof v === 'string') q.value = v })
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.home') }}</span><span class="sep">/</span><span>{{ $t('nav.discover') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.discover') }}</h1>
          <p class="ph-sub">{{ $t('join.discoverSub') }}</p>
        </div>
      </div>
      <div class="dsc-head">
        <label class="input-wrap"><Icon name="search" small /><input v-model="q" class="input" type="search" :placeholder="$t('join.searchPh')" data-testid="discover-q"></label>
        <span class="small faint">{{ $t('join.discoverCount', { n: shown.length }) }}</span>
      </div>
      <div v-if="loadError" class="notice err" data-testid="discover-error"><Icon name="err" /><div class="grow">{{ loadError }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
      <p v-else-if="loading && !rows.length" class="faint">{{ $t('c.loading') }}</p>
      <section v-else class="panel" data-testid="discover-list">
        <div v-if="!shown.length" class="empty">
          <h3>{{ $t('join.discoverEmpty') }}</h3>
          <p>{{ $t('join.discoverEmptyText') }}</p>
        </div>
        <div v-else class="dsc-list">
          <div v-for="r in shown" :key="r.id" class="dsc-row" :data-testid="`discover-${r.ref}`">
            <span class="dsc-ic"><Icon name="folders" /></span>
            <div class="dsc-n">
              <b>{{ hl(r.name)[0] }}<mark v-if="hl(r.name)[1]" class="hl">{{ hl(r.name)[1] }}</mark>{{ hl(r.name)[2] }}</b><span class="ref">{{ r.ref }}</span>
              <p v-if="r.description">{{ hl(r.description)[0] }}<mark v-if="hl(r.description)[1]" class="hl">{{ hl(r.description)[1] }}</mark>{{ hl(r.description)[2] }}</p>
              <p v-else class="faint">{{ $t('join.noDesc') }}</p>
            </div>
            <div class="dsc-own"><span class="m6av">{{ (r.owner ?? '?').charAt(0).toUpperCase() }}</span>{{ r.owner ?? '—' }}</div>
            <div class="dsc-dev"><b>{{ r.devices }}</b>{{ $t('join.devices') }}</div>
            <div class="dsc-act">
              <template v-if="r.my_status === 'owner' || r.my_status === 'member'">
                <ProjRole v-if="r.my_role && r.my_status === 'member'" :role="r.my_role" />
                <span v-else class="jst approved"><Icon name="check" small />{{ $t('join.mine') }}</span>
                <router-link class="btn btn-sm" :to="{ name: 'devices', params: { project: r.ref } }">{{ $t('projects.open') }}</router-link>
              </template>
              <template v-else-if="r.my_status === 'pending'">
                <span class="jst pending"><Icon name="clock" small />{{ $t('join.st.pending') }}</span>
                <button class="btn btn-sm" type="button" :data-testid="`discover-cancel-${r.ref}`" @click="cancel(r)">{{ $t('join.cancel') }}</button>
              </template>
              <template v-else>
                <span v-if="r.my_status === 'declined'" class="small faint" :title="$t('join.declinedBeforeTip')">{{ $t('join.declinedBefore') }}</span>
                <button class="btn btn-sm btn-primary" type="button" :disabled="ro" :data-testid="`discover-ask-${r.ref}`" @click="ask(r)"><Icon name="userPlus" small />{{ $t('join.askJoin') }}</button>
              </template>
            </div>
          </div>
        </div>
      </section>
      <div class="dsc-note"><Icon name="lock" small /><span>{{ $t('join.publicOnly') }}</span></div>
    </div>

    <div v-if="cur" class="modal-back" @click.self="cur = null">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="jrT" style="width: min(560px, 100%)" data-testid="join-dialog">
        <div class="modal-h"><h2 id="jrT">{{ $t('join.askJoinTitle') }}</h2><button class="btn btn-sm btn-icon btn-ghost" type="button" :aria-label="$t('c.close')" @click="cur = null"><Icon name="x" /></button></div>
        <div class="modal-b">
          <div class="req-proj"><span class="dsc-ic"><Icon name="folders" /></span><div><b>{{ cur.name }}</b><small>{{ cur.ref }} · {{ $t('join.nDevices', { n: cur.devices }) }}</small></div></div>
          <div class="field">
            <span class="field-label">{{ $t('join.roleWanted') }}</span>
            <div class="role-pick">
              <label class="radio-card"><input v-model="role" type="radio" value="read" data-testid="join-role-read"><div><div class="rc-t">{{ $t('proj.role.read') }}</div><div class="rc-d">{{ $t('join.roleReadDesc') }}</div></div></label>
              <label class="radio-card"><input v-model="role" type="radio" value="edit" data-testid="join-role-edit"><div><div class="rc-t">{{ $t('proj.role.edit') }}</div><div class="rc-d">{{ $t('join.roleEditDesc') }}</div></div></label>
            </div>
            <span class="hint">{{ $t('join.roleHint') }}</span>
          </div>
          <div class="field mt16">
            <label for="jrWhy">{{ $t('join.reason') }}</label>
            <textarea id="jrWhy" v-model="reason" class="textarea" rows="3" maxlength="500" :placeholder="$t('join.reasonPh')" data-testid="join-reason" />
            <span class="hint">{{ $t('join.reasonHint') }}</span>
          </div>
          <div v-if="dlgErr" class="notice err mt8"><Icon name="err" /><div>{{ dlgErr }}</div></div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="cur = null">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="button" :disabled="busy" data-testid="join-send" @click="send"><Icon name="send" small />{{ $t('join.sendRequest') }}</button>
        </div>
      </div>
    </div>
    <div v-if="toast" class="toast" role="status" data-testid="discover-toast"><Icon name="check" small /><span>{{ toast }}</span></div>
  </main>
</template>
