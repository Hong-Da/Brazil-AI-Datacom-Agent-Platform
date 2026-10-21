<script setup lang="ts">
/** 我的加入申请（M9-8）：待审批可撤回，已通过可打开，被拒绝可重新申请。 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import ProjRole from '@/components/proj-role.vue'
import { errorText } from '@/api'
import { shortTime } from '@/views/account/account'
import { cancelRequest, statusIcon, type JoinRequest } from './join'

defineProps<{ rows: JoinRequest[] }>()
const emit = defineEmits<{ changed: [msg: string] }>()
const { t } = useI18n()
const err = ref('')

async function cancel(r: JoinRequest): Promise<void> {
  err.value = ''
  try {
    await cancelRequest(r.id)
    emit('changed', t('join.cancelled'))
  } catch (e) {
    err.value = errorText(e)
  }
}
</script>

<template>
  <section class="panel mt16" data-testid="my-join-requests">
    <div class="panel-h"><h2>{{ $t('join.myRequests') }}</h2><span class="meta">{{ $t('join.myRequestsMeta') }}</span></div>
    <div v-if="err" class="notice err" style="margin: 10px 14px"><Icon name="err" /><div>{{ err }}</div></div>
    <div v-for="r in rows" :key="r.id" class="myreq" :data-testid="`my-req-${r.id}`">
      <div>
        <b>{{ r.project.name }}</b> <span class="small faint mono">{{ r.project.ref }}</span>
        <div class="why">{{ r.reason || $t('join.noReason') }}</div>
      </div>
      <div><ProjRole :role="r.decided_role ?? r.role" /></div>
      <div class="small muted">
        <template v-if="r.status === 'pending'">{{ $t('join.sentAt', { t: shortTime(r.created_at) }) }}</template>
        <template v-else-if="r.status === 'approved'">{{ $t('join.approvedBy', { u: r.decided_by ?? '' }) }}</template>
        <template v-else-if="r.status === 'declined'">{{ $t('join.declinedBy', { u: r.decided_by ?? '' }) }}<template v-if="r.note">：{{ r.note }}</template></template>
        <template v-else>{{ shortTime(r.decided_at) }}</template>
      </div>
      <div><span :class="['jst', r.status]"><Icon :name="statusIcon(r.status)" small />{{ $t(`join.st.${r.status}`) }}</span></div>
      <div class="right">
        <button v-if="r.status === 'pending'" class="btn btn-sm" type="button" :data-testid="`my-req-cancel-${r.id}`" @click="cancel(r)">{{ $t('join.cancel') }}</button>
        <router-link v-else-if="r.status === 'approved'" class="btn btn-sm" :to="{ name: 'devices', params: { project: r.project.ref } }"><Icon name="enter" small />{{ $t('projects.open') }}</router-link>
        <router-link v-else class="btn btn-sm" :to="{ name: 'discover', query: { q: r.project.name } }">{{ $t('join.askAgain') }}</router-link>
      </div>
    </div>
  </section>
</template>
