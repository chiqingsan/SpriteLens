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
