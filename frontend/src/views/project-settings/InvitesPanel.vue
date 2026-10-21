<script setup lang="ts">
/**
 * 项目设置：邀请链接（M9-8，属主、“管理”成员、管理员）。新建时选角色、有效期、是否仍需审批；链接只在新建后显示一次
 * （服务器只存指纹）；可以撤销。
 */
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import ProjRole from '@/components/proj-role.vue'
import { errorText } from '@/api'
import { shortTime } from '@/views/account/account'
import { createInvite, EXPIRY_DAYS, inviteUrl, listInvites, revokeInvite, statusIcon, type Invite, type MemberRole } from '@/views/join/join'

const props = defineProps<{ projectRef: string }>()
const emit = defineEmits<{ changed: [msg: string] }>()
const { t } = useI18n()
const rows = ref<Invite[]>([])
const err = ref('')
const once = ref('')
const open = ref(false)
const role = ref<MemberRole>('read')
const days = ref<number>(7)
const approval = ref(false)
const note = ref('')
const busy = ref(false)

async function load(): Promise<void> {
  err.value = ''
  try { rows.value = (await listInvites(props.projectRef)).invites } catch (e) { err.value = errorText(e) }
}
function start(): void {
  role.value = 'read'
  days.value = 7
  approval.value = false
  note.value = ''
  open.value = true
}
async function create(): Promise<void> {
  busy.value = true
  err.value = ''
  try {
    const inv = await createInvite(props.projectRef, { role: role.value, days: days.value, requires_approval: approval.value, note: note.value.trim() })
    once.value = inviteUrl(inv.path ?? '')
    open.value = false
    await load()
  } catch (e) {
    err.value = errorText(e)
  } finally {
    busy.value = false
  }
}
async function copy(): Promise<void> {
  try { await navigator.clipboard.writeText(once.value); emit('changed', t('join.copied')) } catch { /* 浏览器不允许时手动选中复制 */ }
}
async function revoke(v: Invite): Promise<void> {
  err.value = ''
  try {
    await revokeInvite(props.projectRef, v.id)
    emit('changed', t('join.revokedToast'))
    await load()
  } catch (e) {
    err.value = errorText(e)
  }
}
onMounted(load)
watch(() => props.projectRef, load)
</script>

<template>
  <section id="s-invites" class="panel ps-sec" data-testid="ps-invites">
    <div class="panel-h">
      <h2>{{ $t('join.invites') }}</h2>
      <span class="meta">{{ $t('join.invitesMeta') }}</span>
      <button class="btn btn-sm btn-primary ml-auto" type="button" data-testid="inv-new" @click="start"><Icon name="plus" small />{{ $t('join.newInvite') }}</button>
    </div>
    <div v-if="err" class="notice err" style="margin: 10px 14px"><Icon name="err" /><div>{{ err }}</div></div>
    <div v-if="once" class="panel-b" style="padding-bottom: 0">
      <div class="inv-once" data-testid="invite-once">
        <p><b>{{ $t('join.onceTitle') }}</b></p>
        <div class="url"><input class="input" readonly :value="once" data-testid="invite-url" @focus="($event.target as HTMLInputElement).select()"><button class="btn" type="button" @click="copy"><Icon name="copy" small />{{ $t('join.copy') }}</button></div>
      </div>
    </div>
    <div v-if="!rows.length" class="empty small"><h3>{{ $t('join.noInvites') }}</h3></div>
    <div v-else class="tbl-wrap">
      <table class="tbl inv-tbl">
        <thead><tr><th>{{ $t('join.colLink') }}</th><th>{{ $t('join.colRole') }}</th><th>{{ $t('join.colApproval') }}</th><th>{{ $t('join.colExpires') }}</th><th class="num">{{ $t('join.colUses') }}</th><th>{{ $t('join.colState') }}</th><th>{{ $t('join.colBy') }}</th><th /></tr></thead>
        <tbody>
          <tr v-for="v in rows" :key="v.id" :class="{ 'is-dead': v.state !== 'active' }" :data-testid="`inv-${v.prefix}`">
            <td><span class="tokp">…/invite/lmi_{{ v.prefix }}…</span><div v-if="v.note" class="small faint">{{ v.note }}</div></td>
            <td><ProjRole :role="v.role" /></td>
            <td><span v-if="v.requires_approval" class="tag t-amber">{{ $t('join.needsApproval') }}</span><span v-else class="small faint">{{ $t('join.joinsDirectly') }}</span></td>
            <td class="small">{{ shortTime(v.expires_at) }}</td>
            <td class="num">{{ v.uses }}</td>
            <td><span :class="['jst', v.state]"><Icon :name="statusIcon(v.state)" small />{{ $t(`join.st.${v.state}`) }}</span></td>
            <td class="small muted">{{ v.created_by }}</td>
            <td class="right"><button v-if="v.state === 'active'" class="btn btn-sm" type="button" :data-testid="`inv-revoke-${v.prefix}`" @click="revoke(v)">{{ $t('join.revoke') }}</button></td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="open" class="modal-back" @click.self="open = false">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="ivT" style="width: min(560px, 100%)" data-testid="invite-dialog">
        <div class="modal-h"><h2 id="ivT">{{ $t('join.newInviteTitle') }}</h2><button class="btn btn-sm btn-icon btn-ghost" type="button" :aria-label="$t('c.close')" @click="open = false"><Icon name="x" /></button></div>
        <div class="modal-b">
          <div class="field">
            <span class="field-label">{{ $t('join.roleAfter') }}</span>
            <div class="seg" role="group" data-testid="inv-role">
              <button v-for="r in (['read', 'edit', 'manage'] as const)" :key="r" type="button" :aria-pressed="role === r" :data-role="r" @click="role = r">{{ $t(`proj.role.${r}`) }}</button>
            </div>
          </div>
          <div class="field mt16">
            <span class="field-label">{{ $t('join.expiresAfter') }}</span>
            <div class="seg" role="group" data-testid="inv-days">
              <button v-for="d in EXPIRY_DAYS" :key="d" type="button" :aria-pressed="days === d" @click="days = d">{{ $t('join.nDays', { n: d }) }}</button>
            </div>
            <span class="hint">{{ $t('join.expiresHint') }}</span>
          </div>
          <label class="radio-card mt16 chk"><input v-model="approval" type="checkbox" data-testid="inv-approval"><div><div class="rc-t">{{ $t('join.stillApproval') }}</div><div class="rc-d">{{ $t('join.stillApprovalHint') }}</div></div></label>
          <div class="field mt16">
            <label for="ivNote">{{ $t('join.noteOptional') }}</label>
            <input id="ivNote" v-model="note" class="input" maxlength="200" :placeholder="$t('join.inviteNotePh')">
          </div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="open = false">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="button" :disabled="busy" data-testid="inv-create" @click="create"><Icon name="link" small />{{ $t('join.createLink') }}</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.chk { display: flex; gap: 10px; }
</style>
