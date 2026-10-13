<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Egg } from '../types/eggDex'
const props = defineProps<{ egg: Egg }>()
const failed = ref(0)
const source = computed(() => failed.value === 0 ? props.egg.egg_icon_url || props.egg.icon_url
  : failed.value === 1 && props.egg.egg_icon_url ? props.egg.icon_url : '')
</script>
<template>
  <span class="hb-art">{{ egg.name.slice(0, 1) || '?' }}<img v-if="source" :src="source" alt="" loading="lazy" @error="failed++"></span>
</template>
