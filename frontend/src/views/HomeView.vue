<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api'

interface Health {
  version: string
  configured: boolean
  database: { backend: string; ok: boolean }
  knowledge: { dir: string; exists: boolean }
  ai: { configured: boolean }
}
const health = ref<Health | null>(null)
const error = ref('')
onMounted(async () => {
  try {
    health.value = await api<Health>('/health')
  } catch (e) {
    error.value = (e as Error).message
  }
})
</script>

<template>
  <section class="home">
    <h1>{{ $t('home.title') }}</h1>
    <p class="dim">{{ $t('home.subtitle') }}</p>
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />
    <el-descriptions v-if="health" :column="1" border data-testid="status">
      <el-descriptions-item :label="$t('home.version')">{{ health.version }}</el-descriptions-item>
      <el-descriptions-item :label="$t('home.database')">
        {{ health.database.backend }} · {{ health.database.ok ? $t('common.ok') : $t('common.unavailable') }}
      </el-descriptions-item>
      <el-descriptions-item :label="$t('home.knowledge')">
        <span class="mono">{{ health.knowledge.dir }}</span>
      </el-descriptions-item>
      <el-descriptions-item :label="$t('home.ai')">
        {{ health.ai.configured ? $t('home.aiOn') : $t('home.aiOff') }}
      </el-descriptions-item>
    </el-descriptions>
  </section>
</template>

<style scoped>
.home { max-width: 860px; }
.dim { color: var(--lm-text-dim); }
</style>
