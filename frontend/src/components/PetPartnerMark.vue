<script setup lang="ts">
import type { PetSummary } from '../types/pets'

defineProps<{ pet: PetSummary }>()
</script>

<template>
  <span
    v-if="pet.partner_mark"
    class="pet-partner-mark"
    role="img"
    :aria-label="pet.partner_mark.name"
    :title="pet.partner_mark.name"
  >
    <img class="pet-partner-mark-frame" :src="pet.partner_mark.frame_url" alt="" aria-hidden="true">
    <img class="pet-partner-mark-icon" :src="pet.partner_mark.icon_url" :alt="pet.partner_mark.name">
  </span>
</template>
