<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { EggBoxEntry } from '../types/eggBox'

const props = defineProps<{ egg: EggBoxEntry; size: 'card' | 'hero' }>()
const failed = ref(0)
const source = computed(() => failed.value === 0
  ? props.egg.icon_url || props.egg.fallback_icon_url
  : failed.value === 1 && props.egg.icon_url ? props.egg.fallback_icon_url : '')
watch(() => [props.egg.icon_url, props.egg.fallback_icon_url], () => { failed.value = 0 })
</script>

<template>
  <span class="eggbox-artwork" :class="`eggbox-artwork--${size}`" aria-hidden="true">
    <img v-if="source" :src="source" alt="" loading="lazy" decoding="async" @error="failed++">
    <span v-else class="eggbox-artwork-placeholder">?</span>
  </span>
</template>
