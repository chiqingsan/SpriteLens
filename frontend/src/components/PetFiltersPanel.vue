<script setup lang="ts">
import type { PetFilterModel } from '../composables/usePetFilters'
import type { PetAdvancedModel } from '../composables/usePetAdvancedFilters'
import type { PetConditions, PetShortcut } from '../types/petConditions'
import PetBasicFilters from './PetBasicFilters.vue'
import PetAdvancedFilters from './PetAdvancedFilters.vue'
import PetShortcuts from './PetShortcuts.vue'
import UiIcon from './UiIcon.vue'
import { ref } from 'vue'
defineProps<{ basic: PetFilterModel; advanced: PetAdvancedModel; applied: Partial<PetConditions>; items: PetShortcut[]; busy: () => boolean; persist: (items: PetShortcut[]) => Promise<void>; reload: () => void; reset: () => void; notify: (message: string, bad: boolean) => void }>()
const shortcuts = ref<InstanceType<typeof PetShortcuts>>()
defineExpose({ cancel: () => shortcuts.value?.cancel() })
</script>
<template>
  <Teleport to="#pet-filter-actions">
    <div class="segmented filter-match-mode" aria-label="筛选匹配方式"><button v-for="mode in (['and', 'or'] as const)" :key="mode" :aria-pressed="basic.filters.pool_mode === mode" :class="{ active: basic.filters.pool_mode === mode }" :title="mode === 'and' ? '全符合' : '任一符合'" @click="basic.patch({ pool_mode: mode })">{{ mode.toUpperCase() }}</button></div>
    <button id="btn-reset-filters" class="ghost-button small" @click="reset"><UiIcon name="filter-off"></UiIcon>重置</button>
  </Teleport>
  <PetShortcuts ref="shortcuts" :basic="basic" :advanced="advanced" :applied="applied" :items="items" :busy="busy" :persist="persist" :reload="reload" :notify="notify"></PetShortcuts>
  <div class="quick-filter-head detail-filter-head"><h3>详细条件</h3></div>
  <div class="pet-detail-filters"><PetBasicFilters :model="basic"></PetBasicFilters><PetAdvancedFilters :model="advanced" :basic="basic"></PetAdvancedFilters></div>
</template>
