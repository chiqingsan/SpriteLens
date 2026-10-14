<script setup lang="ts">
import { ref, watch } from 'vue'

const { src, alt, placeholder } = defineProps<{ src: string; alt: string; placeholder: string }>()
const failed = ref(false)
watch(() => src, () => { failed.value = false })
</script>

<template>
  <div class="detail-art-stage">
    <img v-if="src && !failed" class="detail-artwork" :src="src" :alt="alt" @error="failed = true">
    <span v-else class="detail-art-placeholder">{{ placeholder }}</span>
  </div>
</template>
