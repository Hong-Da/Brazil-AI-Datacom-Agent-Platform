<script setup lang="ts">
/**
 * 账号管理：创建项目的权限（M9-8，REQ-050，预览 M9-8/accounts.html）。顶部说明总开关“普通用户可以创建项目”的状态
 * （在系统设置里改）；下面是待处理的创建权限申请：授权（即给该账号单独授权）或拒绝。
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText } from '@/api'
import { useNotify } from '@/stores/notify'
import { shortTime } from '@/views/account/account'
import { approveCreate, declineCreate, listCreateRequests, type CreateRequest } from '@/views/join/join'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ changed: [msg: string] }>()
const { t } = useI18n()
const notify = useNotify()
const rows = ref<CreateRequest[]>([])
const err = ref('')
const busy = ref<number | null>(null)

async function load(): Promise<void> {
  try { rows.value = (await listCreateRequests()).requests } catch (e) { err.value = errorText(e) }
}
async function decide(r: CreateRequest, ok: boolean): Promise<void> {
  busy.value = r.id
  err.value = ''
  try {
    if (ok) await approveCreate(r.id)
    else await declineCreate(r.id)
    emit('changed', t(ok ? 'join.grantedToast' : 'join.createDeclinedToast', { u: r.username }))
    void notify.refresh()
    await load()
  } catch (e) {
    err.value = errorText(e)
  } finally {
    busy.value = null
  }
}
onMounted(load)
defineExpose({ load })
</script>

<template>
  <div class="cp-strip" data-testid="create-switch-strip">
    <Icon name="folders" />
    <span>{{ $t('join.switchLabel') }} <span class="off">{{ open ? $t('join.on') : $t('join.off') }}</span></span>
    <span class="small faint grow">{{ open ? $t('join.switchOnText') : $t('join.switchOffText') }}</span>
    <router-link class="btn btn-sm" :to="{ name: 'settings' }"><Icon name="gear" small />{{ $t('join.changeInSettings') }}</router-link>
  </div>
  <section v-if="rows.length || err" class="panel mb16" data-testid="create-requests">
    <div class="panel-h"><h2>{{ $t('join.createRequests') }}</h2><span class="meta">{{ $t('join.nPending', { n: rows.length }) }}</span></div>
    <div v-if="err" class="notice err" style="margin: 10px 14px"><Icon name="err" /><div>{{ err }}</div></div>
    <div v-for="r in rows" :key="r.id" class="cr-row" :data-testid="`cr-${r.username}`">
      <div class="jr-who">
        <span class="m6av">{{ r.username.charAt(0).toUpperCase() }}</span>
        <div><b>{{ r.username }}</b><div class="jr-meta">{{ shortTime(r.created_at) }}</div><div v-if="r.reason" class="jr-reason">{{ r.reason }}</div></div>
      </div>
      <div class="jr-act">
        <button class="btn btn-sm btn-primary" type="button" :disabled="busy === r.id" :data-testid="`cr-grant-${r.username}`" @click="decide(r, true)"><Icon name="check" small />{{ $t('join.grant') }}</button>
        <button class="btn btn-sm" type="button" :disabled="busy === r.id" :data-testid="`cr-decline-${r.username}`" @click="decide(r, false)"><Icon name="x" small />{{ $t('join.decline') }}</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.mb16 { margin-bottom: 16px; }
</style>
