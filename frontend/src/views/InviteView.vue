<script setup lang="ts">
/**
 * 打开邀请链接（M9-8，REQ-050，预览 DevelopDocs/ui-preview/M9-8/invite.html）：没登录时路由先到登录页、登录后回到这里；
 * 显示项目的公开信息与加入后的角色；直接加入，或（链接要求审批时）留言后提交申请；失效、已是成员时给出说明。
 */
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ProjRole from '@/components/proj-role.vue'
import { ApiError, errorText } from '@/api'
import { useAuth } from '@/stores/auth'
import { useProject } from '@/stores/project'
import { shortTime } from '@/views/account/account'
import { acceptInvite, inviteInfo, type InviteInfo } from './join/join'

const route = useRoute()
const router = useRouter()
const auth = useAuth()
const project = useProject()
const token = String(route.params.token ?? '')
const info = ref<InviteInfo | null>(null)
const missing = ref(false)
const loadError = ref('')
const reason = ref('')
const busy = ref(false)
const err = ref('')
const sent = ref(false)

async function load(): Promise<void> {
  try {
    info.value = await inviteInfo(token)
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) missing.value = true
    else loadError.value = errorText(e)
  }
}
async function go(): Promise<void> {
  busy.value = true
  err.value = ''
  try {
    const r = await acceptInvite(token, reason.value.trim())
    if (r.status === 'pending') { sent.value = true; return }
    await project.loadLists().catch(() => null)
    await router.push({ name: 'devices', params: { project: r.project } })
  } catch (e) {
    err.value = errorText(e)
  } finally {
    busy.value = false
  }
}
onMounted(load)
const dead = () => missing.value || (info.value && info.value.state !== 'active')
</script>

<template>
  <main class="main">
    <div class="page">
      <section class="panel inv-land" data-testid="invite-card">
        <div class="panel-b">
          <p v-if="!info && !dead() && !loadError" class="faint">{{ $t('c.loading') }}</p>
          <div v-else-if="loadError" class="notice err"><Icon name="err" /><div>{{ loadError }}</div></div>
          <div v-else-if="dead()" class="empty" data-testid="invite-dead">
            <Icon name="clock" />
            <h3>{{ $t('join.inviteDead') }}</h3>
            <p>{{ $t(info?.state === 'revoked' ? 'join.inviteRevokedText' : missing ? 'join.inviteMissingText' : 'join.inviteExpiredText') }}</p>
            <div class="acts center">
              <router-link class="btn" :to="{ name: 'discover' }"><Icon name="search" small />{{ $t('nav.discover') }}</router-link>
              <router-link class="btn" :to="{ name: 'projects' }">{{ $t('nav.projects') }}</router-link>
            </div>
          </div>
          <template v-else-if="info">
            <div class="proj"><span class="dsc-ic"><Icon name="folders" /></span><div><h2>{{ info.project.name }}</h2><div class="small faint mono">{{ info.project.ref }}</div></div></div>
            <div v-if="info.my_status === 'owner' || info.my_status === 'member'" data-testid="invite-member">
              <div class="notice ok"><Icon name="ok" /><div>{{ $t('join.inviteAlready') }} <ProjRole :role="info.my_role" /></div></div>
              <div class="acts mt16"><router-link class="btn btn-primary" :to="{ name: 'devices', params: { project: info.project.ref } }"><Icon name="enter" small />{{ $t('join.openProject') }}</router-link></div>
            </div>
            <div v-else-if="sent || info.my_status === 'pending'" data-testid="invite-sent">
              <div class="req-sent"><Icon name="clock" /><div><b>{{ $t('join.inviteSent') }}</b><br>{{ $t('join.inviteSentText') }}</div></div>
              <div class="acts mt16"><router-link class="btn" :to="{ name: 'projects' }">{{ $t('join.seeMyRequests') }}</router-link></div>
            </div>
            <template v-else>
              <p class="muted">{{ $t(info.requires_approval ? 'join.inviteTextApproval' : 'join.inviteText', { u: info.invited_by }) }}</p>
              <dl class="kvs">
                <dt>{{ $t('join.invitedBy') }}</dt><dd>{{ info.invited_by }}</dd>
                <dt>{{ $t('join.roleAfter') }}</dt><dd><ProjRole :role="info.role" /></dd>
                <dt>{{ $t('join.devicesLabel') }}</dt><dd>{{ info.project.devices }}</dd>
                <dt>{{ $t('join.expires') }}</dt><dd>{{ shortTime(info.expires_at) }}</dd>
              </dl>
              <div v-if="info.requires_approval" class="field mb12">
                <label for="ivWhy">{{ $t('join.message') }}</label>
                <textarea id="ivWhy" v-model="reason" class="textarea" rows="2" maxlength="500" data-testid="invite-reason" />
              </div>
              <div v-if="err" class="notice err mb12"><Icon name="err" /><div>{{ err }}</div></div>
              <div class="acts">
                <router-link class="btn" :to="{ name: 'projects' }">{{ $t('join.notNow') }}</router-link>
                <button class="btn btn-primary" type="button" :disabled="busy || !!auth.me?.read_only" data-testid="invite-go" @click="go">
                  <Icon :name="info.requires_approval ? 'send' : 'userPlus'" small />{{ $t(info.requires_approval ? 'join.sendRequest' : 'join.joinProject') }}
                </button>
              </div>
            </template>
          </template>
        </div>
      </section>
      <p class="small faint center">{{ $t('join.inviteLoginNote') }}</p>
    </div>
  </main>
</template>

<style scoped>
.center { text-align: center; justify-content: center; }
.mb12 { margin-bottom: 12px; }
</style>
