<script setup lang="ts">
/** 删除项目（D-0173）：GET delete-preview 列出连带删除的内容，输入项目标识确认后 DELETE /projects/{p}?confirm=。 */
import { computed, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { del, errorText, get } from '@/api'
import { confirmMatches } from './logic'

interface Preview {
  project: { id: number; slug: string; name: string }
  counts: { private_devices: number; versions: number; refs: number; check_projects: number; scripts: number; check_ignores: number; members: number }
}
const props = defineProps<{ project: { slug: string; ref: string; name: string } }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'deleted'): void }>()

const pv = ref<Preview | null>(null)
const loadError = ref('')
const input = ref('')
const busy = ref(false)
const error = ref('')
const ok = computed(() => !!pv.value && confirmMatches(input.value, props.project.slug) && !busy.value)
const path = () => `/projects/${encodeURIComponent(props.project.ref)}`

async function load(): Promise<void> {
  loadError.value = ''
  try { pv.value = await get<Preview>(`${path()}/delete-preview`) } catch (e) { loadError.value = errorText(e) }
}
onMounted(load)

async function confirm(): Promise<void> {
  if (!ok.value) return
  busy.value = true
  error.value = ''
  try {
    await del(`${path()}?confirm=${encodeURIComponent(input.value.trim())}`)
    emit('deleted')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="modal-back" data-testid="project-delete-modal" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div class="modal" style="width: min(560px, 100%)" role="dialog" aria-modal="true" aria-labelledby="pdT">
      <div class="modal-h">
        <h2 id="pdT">{{ $t('projects.dlg.delTitle') }}</h2>
        <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="emit('close')"><Icon name="x" /></button>
      </div>
      <div class="modal-b stack-12">
        <p class="muted">{{ $t('projects.dlg.delWhat', { p: project.name }) }}</p>
        <div v-if="loadError" class="notice err"><Icon name="err" /><div class="grow">{{ loadError }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
        <p v-else-if="!pv" class="faint">{{ $t('projects.dlg.loading') }}</p>
        <div v-else class="impact" data-testid="pd-impact">
          <div class="del"><Icon name="trash" small /><span>{{ $t('projects.dlg.delPrivate') }}</span><b>{{ pv.counts.private_devices }}</b></div>
          <div class="del"><Icon name="trash" small /><span>{{ $t('projects.dlg.delVersions') }}</span><b>{{ pv.counts.versions }}</b></div>
          <div class="del"><Icon name="trash" small /><span>{{ $t('projects.dlg.delScripts') }}</span><b>{{ pv.counts.scripts }}</b></div>
          <div class="del"><Icon name="trash" small /><span>{{ $t('projects.dlg.delGroups') }}</span><b>{{ pv.counts.check_projects }}</b></div>
          <div class="del"><Icon name="trash" small /><span>{{ $t('projects.dlg.delIgnores') }}</span><b>{{ pv.counts.check_ignores }}</b></div>
          <div class="keep"><Icon name="link" small /><span>{{ $t('projects.dlg.delRefs') }}</span><b>{{ pv.counts.refs }}</b></div>
          <div class="keep"><Icon name="users" small /><span>{{ $t('projects.dlg.delMembers') }}</span><b>{{ pv.counts.members }}</b></div>
        </div>
        <div class="field">
          <label for="pdName">{{ $t('projects.dlg.delConfirm', { s: project.slug }) }}</label>
          <input id="pdName" v-model="input" class="input mono" autocomplete="off" data-testid="pd-confirm" @keydown.enter="confirm">
        </div>
        <div v-if="error" class="notice err" data-testid="pd-error"><Icon name="err" /><div>{{ error }}</div></div>
      </div>
      <div class="modal-f">
        <span class="small faint" style="margin-right: auto">{{ $t('projects.dlg.delFoot') }}</span>
        <button class="btn" type="button" @click="emit('close')">{{ $t('c.cancel') }}</button>
        <button class="btn btn-danger-solid" type="button" :disabled="!ok" data-testid="pd-ok" @click="confirm"><Icon name="trash" small />{{ busy ? $t('projects.busy') : $t('projects.dlg.delOk') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stack-12 { display: flex; flex-direction: column; gap: 12px; }
.btn-danger-solid:disabled { opacity: .5; cursor: not-allowed; }
</style>
