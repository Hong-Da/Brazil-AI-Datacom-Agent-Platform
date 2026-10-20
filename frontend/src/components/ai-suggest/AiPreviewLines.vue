<script setup lang="ts">
/** 代码给出的预览行（M8-4 变更与割接组）：紫色左条是来自 AI 的内容，普通的是代码生成或补发的，红色是被拒绝的部分，
 *  琥珀色是代码无法确认的行。改动与生成的脚本、方案段落与步骤命令、目标写法的解析、映射表、模板与等价核对都用它。 */
import type { PreviewLine } from './logic'

defineProps<{ lines: PreviewLine[] }>()
</script>

<template>
  <div class="pvl mono" data-testid="ai-sg-preview">
    <div v-for="(ln, i) in lines" :key="i" class="pl" :class="`k-${ln.k}`" :data-k="ln.k">{{ ln.text || ' ' }}</div>
  </div>
</template>

<style scoped>
.pvl { border: 1px solid var(--line); border-radius: 5px; background: var(--surface); max-height: 260px; overflow: auto; font-size: 12px; padding: 4px 0; }
.pl { white-space: pre; padding: 0 10px 0 9px; border-left: 3px solid transparent; line-height: 18px; }
.k-ai { border-left-color: var(--ai, var(--violet)); color: var(--ink); }
.k-code { color: var(--ink-2); }
.k-frame { color: var(--ink-3); }
.k-bad { border-left-color: var(--red); color: var(--red-ink); text-decoration: line-through; }
.k-warn { border-left-color: var(--amber); color: var(--amber-ink); }
</style>
