<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { PetSummary } from '../types/pets'
const props = defineProps<{ pet: PetSummary; klass: string; imageMode: string }>()
const url = computed(() => props.imageMode === 'artwork' ? props.pet.artwork_url : props.pet.portrait_url)
const failed = ref(false)
watch(url, () => { failed.value = false })
</script>
<template>
  <span class="pet-image" :class="[klass, { 'is-artwork': imageMode === 'artwork' }]"><span aria-hidden="true">{{ (pet.name || '?').slice(0, 1) }}</span><img v-if="url && !failed" :src="url" alt="" loading="lazy" @error="failed = true"></span>
</template>
