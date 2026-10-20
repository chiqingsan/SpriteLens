<script setup lang="ts">
import { ref, watch } from 'vue'
const { src, name, eager = false } = defineProps<{ src: string; name: string; eager?: boolean }>()
const failed = ref(false)
const loaded = ref(false)
watch(() => src, () => { failed.value = false; loaded.value = false })
</script>
<template>
  <span class="dex-art" :class="{ 'is-loading': src && !failed && !loaded, 'is-loaded': loaded }"><img v-if="src && !failed" :src="src" :alt="name" :loading="eager ? 'eager' : 'lazy'" decoding="async" @load="loaded = true" @error="failed = true"><span v-else aria-hidden="true">{{ name.slice(0, 1) || '?' }}</span></span>
</template>
