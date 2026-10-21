<script setup lang="ts">
/** 项目设置：加入申请（M9-8，属主、“管理”成员、管理员）。通过时可以改角色（可给“管理”），拒绝可写说明。 */
import { onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import ProjRole from '@/components/proj-role.vue'
import { errorText } from '@/api'
import { useNotify } from '@/stores/notify'
import { shortTime } from '@/views/account/account'
import { approveRequest, declineRequest, listRequests, type JoinRequest, type MemberRole } from '@/views/join/join'

const props = defineProps<{ projectRef: string }>()
const emit = defineEmits<{ changed: [msg: string]; count: [n: number] }>()
const { t } = useI18n()
const notify = useNotify()
const rows = ref<JoinRequest[]>([])
const roles = reactive<Record<number, MemberRole>>({})
const notes = reactive<Record<number, string>>({})
const declining = ref<number | null>(null)
const busy = ref<number | null>(null)
const err = ref('')

async function load(): Promise<void> {
  err.value = ''
  try {
    rows.value = (await listRequests(props.projectRef)).requests
    for (const r of rows.value) roles[r.id] = roles[r.id] ?? r.role
    emit('count', rows.value.length)
  } catch (e) {
    err.value = errorText(e)
  }
}
async function approve(r: JoinRequest): Promise<void> {
  busy.value = r.id
  err.value = ''
  try {
    await approveRequest(props.projectRef, r.id, roles[r.id])
    emit('changed', t('join.approvedToast', { u: r.username }))
    void notify.refresh()
    await load()
  } catch (e) {
    err.value = errorText(e)
  } finally {
    busy.value = null
  }
}
async function decline(r: JoinRequest): Promise<void> {
  busy.value = r.id
  err.value = ''
  try {
    await declineRequest(props.projectRef, r.id, (notes[r.id] ?? '').trim())
    declining.value = null
    emit('changed', t('join.declinedToast', { u: r.username }))
    void notify.refresh()
    await load()
  } catch (e) {
    err.value = errorText(e)
  } finally {
    busy.value = null
  }
}
onMounted(load)
watch(() => props.projectRef, load)
</script>

<template>
  <section id="s-requests" class="panel ps-sec" data-testid="ps-requests">
    <div class="panel-h"><h2>{{ $t('join.requests') }}</h2><span class="meta">{{ $t('join.requestsMeta') }}</span></div>
    <div v-if="err" class="notice err" style="margin: 10px 14px"><Icon name="err" /><div>{{ err }}</div></div>
    <div v-if="!rows.length" class="empty small"><h3>{{ $t('join.noPending') }}</h3></div>
    <div v-for="r in rows" :key="r.id" class="jr" :data-testid="`jr-${r.username}`">
      <div class="jr-who">
        <span class="m6av">{{ r.username.charAt(0).toUpperCase() }}</span>
        <div style="min-width: 0">
          <b>{{ r.username }}</b>
          <div class="jr-meta">
            <span>{{ $t('join.asksFor') }}</span><ProjRole :role="r.role" /><span>· {{ shortTime(r.created_at) }}</span>
            <span class="via">{{ r.via === 'invite' ? $t('join.viaInvite', { p: r.invite_prefix ?? '' }) : $t('join.viaSearch') }}</span>
          </div>
          <div v-if="r.reason" class="jr-reason">{{ r.reason }}</div>
          <div v-else class="jr-meta">{{ $t('join.noReason') }}</div>
        </div>
      </div>
      <div class="jr-act">
        <template v-if="declining === r.id">
          <input v-model="notes[r.id]" class="input" style="width: 220px; height: 30px" maxlength="500" :placeholder="$t('join.notePh')" :data-testid="`jr-note-${r.username}`">
          <button class="btn btn-sm btn-danger" type="button" :disabled="busy === r.id" :data-testid="`jr-decline-ok-${r.username}`" @click="decline(r)">{{ $t('join.decline') }}</button>
          <button class="btn btn-sm btn-ghost" type="button" @click="declining = null">{{ $t('c.cancel') }}</button>
        </template>
        <template v-else>
          <select v-model="roles[r.id]" class="select" :aria-label="$t('join.roleGiven')" :data-testid="`jr-role-${r.username}`">
            <option value="read">{{ $t('proj.role.read') }}</option>
            <option value="edit">{{ $t('proj.role.edit') }}</option>
            <option value="manage">{{ $t('proj.role.manage') }}</option>
          </select>
          <button class="btn btn-sm btn-primary" type="button" :disabled="busy === r.id" :data-testid="`jr-approve-${r.username}`" @click="approve(r)"><Icon name="check" small />{{ $t('join.approve') }}</button>
          <button class="btn btn-sm" type="button" :disabled="busy === r.id" :data-testid="`jr-decline-${r.username}`" @click="declining = r.id"><Icon name="x" small />{{ $t('join.decline') }}</button>
        </template>
      </div>
    </div>
  </section>
</template>
