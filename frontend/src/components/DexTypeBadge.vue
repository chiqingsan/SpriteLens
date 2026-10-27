<script setup lang="ts">
import { typeBadgeStyle } from './handbookDisplay'

const props = defineProps<{
  name: string
  color?: string
  iconUrl?: string
  compact?: boolean
}>()
</script>

<template>
  <span class="dex-type-badge" :class="{ compact: props.compact }" :style="typeBadgeStyle(props.color)">
    <img v-if="props.iconUrl" :src="props.iconUrl" alt="" loading="lazy" decoding="async">
    <span>{{ props.name }}</span>
  </span>
</template>

<style>
.dex-type-badge { display: inline-flex; align-items: center; justify-content: center; gap: var(--space-1); min-width: 0; padding: 1px var(--space-2); border: 1px solid color-mix(in srgb, currentColor 20%, var(--line-soft)); border-radius: 999px; font-size: var(--fs-3xs); line-height: 1.3; white-space: nowrap; }
.dex-type-badge img { width: 20px; height: 20px; flex: none; object-fit: contain; }
.dex-type-badge.compact { padding: 1px var(--space-2); font-size: var(--fs-3xs); }
.dex-type-badge.compact img { width: 16px; height: 16px; }
</style>
