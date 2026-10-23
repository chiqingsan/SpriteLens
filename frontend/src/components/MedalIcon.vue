<script setup lang="ts">
import { computed } from 'vue'

// 奖牌名 → 本地图标编号（与图鉴、配窝结果共用的四个繁育奖牌）。
const markIds: Record<string, number> = { '大块头': 1001, '小不点': 1002, '婉转声': 1026, '粗嗓门': 1025 }
const props = defineProps<{ name: string; source?: string }>()
const id = computed(() => markIds[props.name] ?? null)
</script>
<template>
  <img
    v-if="id"
    class="medal-icon"
    :src="`/static/medal-icons/mark-${id}.webp`"
    :alt="name"
    :title="`${name}${source ? ` · ${source === 'worn' ? '当前佩戴' : '数值参考'}` : ''}`"
    loading="lazy"
    decoding="async"
  >
  <span v-else class="medal-icon-text" :title="`${name}（暂无对应本地图标）`">{{ name }}</span>
</template>
