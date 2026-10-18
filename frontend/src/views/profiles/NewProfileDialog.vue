<script setup lang="ts">
import { reactive, ref } from 'vue'
import { errorText, post } from '@/api'
import Icon from '@/components/Icon.vue'
import type { ProfileRow } from './types'

const props = defineProps<{ profiles: ProfileRow[]; families: string[] }>()
const emit = defineEmits<{ close: []; created: [id: string] }>()

const form = reactive({ id: '', title: '', family: props.families[0] ?? '', inherits: '', version: '', platform: '', software: '' })
const busy = ref(false)
const err = ref('')

/** 选了继承来源时，平台族、平台跟随父 Profile（仍可修改） */
function onInherits() {
  const p = props.profiles.find((x) => x.id === form.inherits)
  if (!p) return
  form.family = p.family
  if (!form.platform) form.platform = p.platform
}

async function submit() {
  busy.value = true
  err.value = ''
  try {
    const r = await post<{ profile: string }>('/kb/profiles', { ...form, id: form.id.trim(), inherits: form.inherits || null })
    emit('created', r.profile)
  } catch (e) {
    const data = (e as { data?: unknown }).data
    err.value = Array.isArray(data) && data.length ? `${errorText(e)}：${data.join('；')}` : errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="modal-back" @click.self="emit('close')">
    <form class="modal" style="width:min(640px,100%)" data-testid="new-profile-dialog" @submit.prevent="submit">
      <div class="modal-h">
        <h2>{{ $t('profiles.newTitle') }}</h2>
        <button type="button" class="btn btn-icon btn-ghost" :aria-label="$t('c.close')" @click="emit('close')"><Icon name="x" /></button>
      </div>
      <div class="modal-b">
        <div class="form-grid">
          <div class="field span2">
            <label>{{ $t('profiles.fId') }}</label>
            <input v-model="form.id" class="input mono" required placeholder="huawei-atn-v800r026" data-testid="new-id">
            <div class="hint">{{ $t('profiles.fIdHint') }}</div>
          </div>
          <div class="field span2">
            <label>{{ $t('profiles.fTitle') }}</label>
            <input v-model="form.title" class="input" data-testid="new-title">
          </div>
          <div class="field">
            <label>{{ $t('profiles.fInherits') }}</label>
            <select v-model="form.inherits" class="select mono" data-testid="new-inherits" @change="onInherits">
              <option value="">{{ $t('profiles.noInherit') }}</option>
              <option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.id }}</option>
            </select>
          </div>
          <div class="field">
            <label>{{ $t('profiles.fFamily') }}</label>
            <select v-model="form.family" class="select mono" data-testid="new-family">
              <option v-for="f in families" :key="f" :value="f">{{ f }}</option>
            </select>
          </div>
          <div class="field span2">
            <label>{{ $t('profiles.fVersion') }}</label>
            <input v-model="form.version" class="input mono" placeholder="^V800R026" data-testid="new-version">
            <div class="hint">{{ $t('profiles.fVersionHint') }}</div>
          </div>
          <div class="field">
            <label>{{ $t('profiles.platform') }}</label>
            <input v-model="form.platform" class="input" data-testid="new-platform">
          </div>
          <div class="field">
            <label>{{ $t('profiles.software') }}</label>
            <input v-model="form.software" class="input mono" data-testid="new-software">
          </div>
        </div>
        <div v-if="form.inherits" class="notice info mt12"><Icon name="info" /><div class="grow small">{{ $t('profiles.newInhNote', { p: form.inherits }) }}</div></div>
        <div v-if="err" class="notice err mt12" data-testid="new-error"><Icon name="err" /><div class="grow small">{{ err }}</div></div>
      </div>
      <div class="modal-f">
        <button type="button" class="btn" @click="emit('close')">{{ $t('c.cancel') }}</button>
        <button type="submit" class="btn btn-primary" :disabled="busy || !form.id.trim()" data-testid="new-submit">{{ $t('profiles.create') }}</button>
      </div>
    </form>
  </div>
</template>
