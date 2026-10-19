<script setup lang="ts">
/** 复制为我的新项目（POST /projects/{p}/copy）：能查看即可，只读成员也可以。 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText, post } from '@/api'
import type { ProjectRow } from '@/stores/project'
import { projectBody, validSlug } from './logic'

const props = defineProps<{ project: { slug: string; ref: string; name: string } }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'copied', p: ProjectRow & { copied?: { devices: number; scripts: number } }): void }>()
const { t } = useI18n()

const name = ref(props.project.name + t('projects.dlg.copySuffix'))
const slug = ref('')
const devices = ref(true)
const scripts = ref(true)
const busy = ref(false)
const error = ref('')
const slugErr = computed(() => !!slug.value.trim() && !validSlug(slug.value.trim()))

async function ok(): Promise<void> {
  if (!name.value.trim() || slugErr.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const r = await post<ProjectRow & { copied?: { devices: number; scripts: number } }>(
      `/projects/${encodeURIComponent(props.project.ref)}/copy`,
      projectBody(name.value, slug.value, { devices: devices.value, scripts: scripts.value }),
    )
    emit('copied', r)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="modal-back" data-testid="project-copy-modal" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div class="modal" style="width: min(620px, 100%)" role="dialog" aria-modal="true" aria-labelledby="cpT">
      <div class="modal-h">
        <h2 id="cpT">{{ $t('projects.dlg.copyTitle') }}</h2>
        <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="emit('close')"><Icon name="x" /></button>
      </div>
      <div class="modal-b stack-12">
        <div class="form-grid">
          <div class="field">
            <label for="cpName">{{ $t('projects.dlg.copyName') }}</label>
            <input id="cpName" v-model="name" :class="['input', { 'is-error': !name.trim() }]" maxlength="200" data-testid="cp-name">
          </div>
          <div class="field">
            <label for="cpSlug">{{ $t('projects.dlg.slug') }}</label>
            <input id="cpSlug" v-model="slug" :class="['input mono', { 'is-error': slugErr }]" maxlength="64" data-testid="cp-slug">
            <div v-if="slugErr" class="err"><Icon name="warn" small /><span>{{ $t('projects.dlg.slugErr') }}</span></div>
            <div v-else class="hint">{{ $t('projects.dlg.slugHint') }}</div>
          </div>
        </div>
        <div class="field">
          <span class="field-label">{{ $t('projects.dlg.copyWith') }}</span>
          <div class="copyopts">
            <label class="check"><input v-model="devices" type="checkbox" data-testid="cp-devices"><span>{{ $t('projects.dlg.copyDevices') }}</span></label>
            <label class="check"><input v-model="scripts" type="checkbox" data-testid="cp-scripts"><span>{{ $t('projects.dlg.copyScripts') }}</span></label>
          </div>
        </div>
        <p class="small muted">{{ $t('projects.dlg.copyAlways') }}</p>
        <p class="small faint">{{ $t('projects.dlg.copyNote') }}</p>
        <div v-if="error" class="notice err"><Icon name="err" /><div>{{ error }}</div></div>
      </div>
      <div class="modal-f">
        <button class="btn" type="button" @click="emit('close')">{{ $t('c.cancel') }}</button>
        <button class="btn btn-primary" type="button" :disabled="busy || !name.trim() || slugErr" data-testid="cp-ok" @click="ok"><Icon name="copy" small />{{ busy ? $t('projects.busy') : $t('projects.dlg.copyOk') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stack-12 { display: flex; flex-direction: column; gap: 12px; }
</style>
