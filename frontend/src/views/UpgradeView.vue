<script setup lang="ts">
/**
 * 升级说明（M6，预览 DevelopDocs/ui-preview/M6/upgrade.html）：升级到 0.6.0 后每个账号第一次登录看到一次。
 * 数字都来自接口：我的项目中迁移来的项目（GET /projects 的 migrated_from 与 counts）、默认项目的删除预览（只读，
 * 取版本数与忽略项数）、公共设备库（GET /public-devices）。“知道了”记下已看（project/upgrade.ts）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import { errorText, get } from '@/api'
import { useAuth } from '@/stores/auth'
import { useProject, type ProjectRow } from '@/stores/project'
import { markUpgradeSeen, migratedProjects } from '@/project/upgrade'

const router = useRouter()
const auth = useAuth()
const project = useProject()

const loading = ref(true)
const error = ref('')
const migrated = ref<ProjectRow[]>([])
const publicCount = ref<number | null>(null)
const preview = ref<{ versions: number; check_ignores: number } | null>(null)
const dontShow = ref(true)

const fromUpgrade = computed(() => migrated.value.find((p) => p.migrated_from?.type === 'upgrade') ?? null)
const fromChecks = computed(() => migrated.value.filter((p) => p.migrated_from?.type === 'check_project'))
const checkDevices = computed(() => fromChecks.value.reduce((a, p) => a + p.counts.private, 0))

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const lists = await project.loadLists()
    migrated.value = migratedProjects(lists.mine)
    try { publicCount.value = (await get<{ devices: unknown[] }>('/public-devices')).devices.length } catch { publicCount.value = null }
    const up = migrated.value.find((p) => p.migrated_from?.type === 'upgrade')
    if (up) {
      try {
        preview.value = (await get<{ counts: { versions: number; check_ignores: number } }>(`/projects/${encodeURIComponent(up.ref)}/delete-preview`)).counts
      } catch { preview.value = null }
    }
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)

function done(to: 'dashboard' | 'open'): void {
  if (dontShow.value && auth.me) markUpgradeSeen(auth.me.username)
  if (to === 'open' && fromUpgrade.value) void router.push({ name: 'devices', params: { project: fromUpgrade.value.ref } })
  else if (to === 'open') void router.push({ name: 'projects' })
  else void router.push({ name: 'dashboard' })
}
</script>

<template>
  <main class="main">
    <div class="page">
      <section class="panel up-panel" data-testid="upgrade">
        <div class="panel-h"><h2>{{ $t('upgrade.title') }}</h2></div>
        <div class="panel-b up-body">
          <div v-if="error" class="notice err"><Icon name="err" /><div class="grow">{{ error }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
          <p v-else-if="loading" class="faint">{{ $t('c.loading') }}</p>
          <template v-else>
            <div class="up-hero">
              <svg class="art" viewBox="0 0 150 104" aria-hidden="true">
                <rect x="8" y="30" width="40" height="44" rx="5" fill="var(--surface-2)" stroke="var(--line-strong)" />
                <path d="M16 42h24M16 50h18M16 58h22" stroke="var(--line-strong)" stroke-width="3" stroke-linecap="round" />
                <path d="M54 52h22" stroke="var(--blue)" stroke-width="2" /><path d="M71 47l6 5-6 5" fill="none" stroke="var(--blue)" stroke-width="2" />
                <rect x="84" y="18" width="58" height="68" rx="7" fill="var(--blue-soft)" stroke="var(--blue-line)" />
                <path d="M84 28a7 7 0 0 1 7-7h16l5 5" fill="none" stroke="var(--blue-line)" />
                <rect x="92" y="36" width="18" height="9" rx="2" fill="var(--blue)" /><rect x="114" y="36" width="20" height="9" rx="2" fill="var(--blue)" />
                <rect x="92" y="50" width="18" height="9" rx="2" fill="var(--blue)" /><rect x="114" y="50" width="20" height="9" rx="2" fill="var(--blue)" />
                <rect x="92" y="66" width="42" height="5" rx="2.5" fill="var(--line-strong)" />
              </svg>
              <p>{{ fromUpgrade ? $t('upgrade.intro') : $t('upgrade.introUser') }}</p>
            </div>
            <p v-if="!migrated.length" class="muted" data-testid="upgrade-none">{{ $t('upgrade.none') }}</p>
            <div class="up-list" data-testid="upgrade-list">
              <template v-if="fromUpgrade">
                <div><Icon name="folder" small /><span>{{ $t('upgrade.defaultMoved', { p: fromUpgrade.name }) }}</span><b>{{ $t('upgrade.nDevices', { n: fromUpgrade.counts.private }) }}</b></div>
                <div v-if="preview"><Icon name="history" small /><span>{{ $t('upgrade.versions') }}</span><b>{{ $t('upgrade.nVersions', { n: preview.versions }) }}</b></div>
                <div v-if="preview"><Icon name="inbox" small /><span>{{ $t('upgrade.ignores') }}</span><b>{{ preview.check_ignores }}</b></div>
              </template>
              <template v-if="fromChecks.length">
                <div><Icon name="file" small /><span>{{ $t('upgrade.checkProjects') }}</span><b>{{ fromChecks.map((p) => p.name).join(' · ') }}</b></div>
                <div><Icon name="server" small /><span>{{ $t('upgrade.baselineCopied') }}</span><b>{{ $t('upgrade.nDevices', { n: checkDevices }) }}</b></div>
              </template>
              <div v-if="publicCount !== null"><Icon name="db" small /><span>{{ publicCount ? $t('upgrade.publicLib') : $t('upgrade.publicEmpty') }}</span><b>{{ publicCount }}</b></div>
              <div v-if="auth.isAdmin"><Icon name="key" small /><span>{{ $t('upgrade.globalToken') }}</span><b /></div>
              <template v-else>
                <div><Icon name="users" small /><span>{{ $t('upgrade.sharedWhere') }}</span><b /></div>
                <div v-if="!auth.isKbEditor"><Icon name="shield" small /><span>{{ $t('upgrade.kbReadOnly') }}</span><b /></div>
              </template>
            </div>
          </template>
        </div>
        <div class="modal-f">
          <label class="check" style="margin-right: auto"><input v-model="dontShow" type="checkbox" data-testid="upgrade-dont-show"><span>{{ $t('upgrade.dontShow') }}</span></label>
          <button class="btn" type="button" data-testid="upgrade-open" @click="done('open')">{{ fromUpgrade ? $t('upgrade.openDefault') : $t('upgrade.openProjects') }}</button>
          <button class="btn btn-primary" type="button" data-testid="upgrade-ok" @click="done('dashboard')">{{ $t('upgrade.gotIt') }}</button>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.up-panel { max-width: 720px; margin: 24px auto; }
.up-body { display: flex; flex-direction: column; gap: 14px; }
.up-hero p { max-width: 60ch; }
</style>
