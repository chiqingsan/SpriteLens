<script setup lang="ts">
import { computed, reactive } from 'vue'
const props = defineProps<{ cardId: string; baseColor: string; mixColor: string; particleId?: number }>()
const failed = reactive<Record<string, boolean>>({})
const special = computed(() => /^(s[1-4]|1000)$/.test(String(props.cardId)))
const pattern = computed(() => ({ 1: 'sparkle_four', 2: 'heart', 3: 'diamond', 4: 'star_outline' }[props.particleId as 1]))
// 普通卡要求两个色值都是六位十六进制，与原生色卡图元同一判据。
const painted = computed(() => /^#[0-9a-f]{6}$/i.test(props.baseColor) && /^#[0-9a-f]{6}$/i.test(props.mixColor))
</script>
<template>
  <img v-if="special && !failed.card" :src="`/static/color-cards/${String(props.cardId).toLowerCase()}.png`" alt="" @error="failed.card = true">
  <template v-else>
    <svg viewBox="0 0 100 60" preserveAspectRatio="none" aria-hidden="true"><rect width="100" height="60" :fill="mixColor"></rect><path d="M0 30 Q25 12 50 30 T100 30 V60 H0 Z" :fill="baseColor"></path></svg>
    <img v-if="pattern && !failed[pattern]" :src="`/static/color-cards/pattern_${pattern}.png`" alt="" @error="failed[pattern] = true">
  </template>
</template>
<style scoped>
svg, img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: fill; }
</style>
