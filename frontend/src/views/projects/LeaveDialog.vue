<script setup lang="ts">
/** 退出项目：成员移除自己（DELETE /projects/{p}/members/{我}）。 */
import { ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { del, errorText } from '@/api'
import { useAuth } from '@/stores/auth'

const props = defineProps<{ project: { slug: string; name: string } }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'left'): void }>()
const auth = useAuth()
const busy = ref(false)
const error = ref('')

async function ok(): Promise<void> {
  if (!auth.me || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await del(`/projects/${encodeURIComponent(props.project.slug)}/members/${encodeURIComponent(auth.me.username)}`)
    emit('left')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="modal-back" data-testid="project-leave-modal" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div class="modal" style="width: min(460px, 100%)" role="dialog" aria-modal="true" aria-labelledby="plT">
      <div class="modal-h">
        <h2 id="plT">{{ $t('projects.leaveTitle') }}</h2>
        <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="emit('close')"><Icon name="x" /></button>
      </div>
      <div class="modal-b">
        <p>{{ $t('projects.leaveText', { p: project.name }) }}</p>
        <div v-if="error" class="notice err mt12"><Icon name="err" /><div>{{ error }}</div></div>
      </div>
      <div class="modal-f">
        <button class="btn" type="button" @click="emit('close')">{{ $t('c.cancel') }}</button>
        <button class="btn btn-danger" type="button" :disabled="busy" data-testid="pl-ok" @click="ok"><Icon name="logout" small />{{ $t('projects.leaveOk') }}</button>
      </div>
    </div>
  </div>
</template>
