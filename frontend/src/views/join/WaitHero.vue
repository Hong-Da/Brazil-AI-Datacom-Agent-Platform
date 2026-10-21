<script setup lang="ts">
/**
 * 没有任何项目、也不能创建项目时的“我的项目”（M9-8，预览 M9-8/projects.html）：等人邀请的提示、三种加入方式，
 * 一键申请创建权限（通知管理员），已申请时显示状态并可撤回。
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText } from '@/api'
import { useAuth } from '@/stores/auth'
import { shortTime } from '@/views/account/account'
import { cancelCreate, requestCreate, type CreatePermission } from './join'

const props = defineProps<{ perm: CreatePermission | null }>()
const emit = defineEmits<{ changed: [msg: string] }>()
const { t } = useI18n()
const auth = useAuth()

const open = ref(false)
const reason = ref('')
const busy = ref(false)
const err = ref('')

async function send(): Promise<void> {
  busy.value = true
  err.value = ''
  try {
    await requestCreate(reason.value.trim())
    open.value = false
    reason.value = ''
    emit('changed', t('join.createSent'))
  } catch (e) {
    err.value = errorText(e)
  } finally {
    busy.value = false
  }
}
async function withdraw(): Promise<void> {
  try {
    await cancelCreate()
    emit('changed', t('join.createWithdrawn'))
  } catch (e) {
    err.value = errorText(e)
  }
}
const pending = () => props.perm?.request?.status === 'pending'
const declined = () => props.perm?.request?.status === 'declined'
</script>

<template>
  <section class="panel" data-testid="projects-wait">
    <div class="wait-hero">
      <svg viewBox="0 0 200 130" width="200" aria-hidden="true" class="wait-art">
        <rect x="16" y="30" width="96" height="74" rx="8" fill="var(--blue-soft)" stroke="var(--blue-line)" />
        <path d="M16 40a8 8 0 0 1 8-8h26l8 8" fill="none" stroke="var(--blue-line)" />
        <rect x="30" y="54" width="68" height="6" rx="3" fill="var(--line-strong)" /><rect x="30" y="68" width="48" height="6" rx="3" fill="var(--line-strong)" />
        <circle cx="150" cy="52" r="16" fill="var(--surface-3)" stroke="var(--line-strong)" />
        <path d="M128 96c4-14 40-14 44 0" fill="none" stroke="var(--line-strong)" stroke-width="2" />
        <path d="M118 66h14" stroke="var(--amber)" stroke-width="2.5" stroke-dasharray="3 3" />
        <circle cx="174" cy="30" r="9" fill="var(--amber-soft)" stroke="var(--amber-line)" />
        <path d="M174 26v5M174 34h.01" stroke="var(--amber-ink)" stroke-width="2" stroke-linecap="round" />
      </svg>
      <div>
        <h2>{{ $t('join.waitTitle') }}</h2>
        <p>{{ $t('join.waitText') }}</p>
        <div class="ways">
          <div><b><Icon name="userPlus" small />{{ $t('join.wayOwner') }}</b>{{ $t('join.wayOwnerText', { u: auth.me?.username ?? '' }) }}</div>
          <div><b><Icon name="search" small />{{ $t('join.waySearch') }}</b>{{ $t('join.waySearchText') }}</div>
          <div><b><Icon name="link" small />{{ $t('join.wayInvite') }}</b>{{ $t('join.wayInviteText') }}</div>
        </div>
        <div class="acts">
          <router-link class="btn btn-primary" :to="{ name: 'discover' }" data-testid="wait-discover"><Icon name="search" small />{{ $t('nav.discover') }}</router-link>
          <button v-if="!pending() && !auth.me?.read_only" class="btn" type="button" data-testid="ask-create" @click="open = true"><Icon name="send" small />{{ $t('join.askCreate') }}</button>
        </div>
        <div v-if="pending()" class="req-sent" data-testid="create-request-pending">
          <Icon name="clock" />
          <div>
            <b>{{ $t('join.createPending') }}</b> · {{ shortTime(perm?.request?.created_at ?? null) }}<br>
            {{ $t('join.createPendingText') }}
            <button class="link-btn" type="button" data-testid="create-withdraw" @click="withdraw">{{ $t('join.withdraw') }}</button>
          </div>
        </div>
        <div v-else-if="declined()" class="notice warn mt8" data-testid="create-request-declined">
          <Icon name="warn" /><div>{{ $t('join.createDeclined', { u: perm?.request?.decided_by ?? '' }) }}<template v-if="perm?.request?.note"> {{ perm.request.note }}</template></div>
        </div>
        <div v-if="err && !open" class="notice err mt8"><Icon name="err" /><div>{{ err }}</div></div>
      </div>
    </div>

    <div v-if="open" class="modal-back" @click.self="open = false">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="crT" style="width: min(520px, 100%)" data-testid="create-request-dialog">
        <div class="modal-h"><h2 id="crT">{{ $t('join.askCreateTitle') }}</h2><button class="btn btn-sm btn-icon btn-ghost" type="button" :aria-label="$t('c.close')" @click="open = false"><Icon name="x" /></button></div>
        <div class="modal-b">
          <p class="small muted mb12">{{ $t('join.askCreateText') }}</p>
          <div class="field">
            <label for="crWhy">{{ $t('join.whatFor') }}</label>
            <textarea id="crWhy" v-model="reason" class="textarea" rows="3" maxlength="500" :placeholder="$t('join.whatForPh')" data-testid="create-reason" />
            <span class="hint">{{ $t('join.max500') }}</span>
          </div>
          <div v-if="err" class="notice err mt8"><Icon name="err" /><div>{{ err }}</div></div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="open = false">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="button" :disabled="busy" data-testid="create-send" @click="send"><Icon name="send" small />{{ $t('join.send') }}</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.mb12 { margin-bottom: 12px; }
</style>
