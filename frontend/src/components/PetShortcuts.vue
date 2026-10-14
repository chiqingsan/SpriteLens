<script setup lang="ts">
import { ref } from 'vue'
import type { PetFilterModel } from '../composables/usePetFilters'
import { measures, type PetAdvancedModel } from '../composables/usePetAdvancedFilters'
import { defaultPetShortcuts, type PetConditions, type PetShortcut } from '../types/petConditions'
import PetShortcutSettings from './PetShortcutSettings.vue'
const props = defineProps<{ basic: PetFilterModel; advanced: PetAdvancedModel; applied: Partial<PetConditions>; items: PetShortcut[]; busy: () => boolean; persist: (items: PetShortcut[]) => Promise<void>; reload: () => void; notify: (message: string, bad: boolean) => void }>()
const settings = ref(false)
const saving = ref(false), error = ref('')
async function save(items: PetShortcut[]) {
  saving.value = true; error.value = ''
  try { await props.persist(items); settings.value = false }
  catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { saving.value = false }
}
function selected(value: Partial<PetConditions>) {
  const current = { ...props.basic.filters, ...props.advanced.filters }
  return Object.entries(value).every(([key, item]) => {
    if (key === 'pool_mode' || key === 'egg_mode' || item === null || item === false || item === 0 || item === ''
      || key === 'level_min' && item === 1 || key === 'level_max' && Number(item) >= 60) return true
    const actual = current[key as keyof PetConditions]
    if (Array.isArray(item)) return Array.isArray(actual) && item.every(entry => new Set<unknown>(actual).has(entry))
    return item === actual
  })
}
function apply(value: Partial<PetConditions>) {
  const basic = props.basic, advanced = props.advanced
  if (selected(value)) {
    const next = { ...basic.filters }
    for (const key of ['natures', 'types', 'medals', 'marks', 'pool'] as const) {
      const removed = new Set<unknown>(value[key] || [])
      Object.assign(next, { [key]: next[key].filter(item => !removed.has(item)) })
    }
    for (const key of ['shiny', 'colorful'] as const) if (value[key]) next[key] = false
    for (const key of ['gender', 'medal', 'speciality', 'acquisition', 'captured_days'] as const) if (value[key]) next[key] = 0
    if (value.search) next.search = ''
    if ((value.level_min ?? 1) > 1 || (value.level_max ?? 60) < 60) { next.level_min = 1; next.level_max = 60 }
    const ranges: Partial<PetConditions> = { egg_groups: advanced.filters.egg_groups.filter(item => !value.egg_groups?.includes(item)) }
    for (const [field] of measures) if (value[`${field}_min`] != null || value[`${field}_max`] != null) {
      ranges[`${field}_min`] = null; ranges[`${field}_max`] = null
    }
    basic.patch(next, false); advanced.patch(ranges, false); props.reload(); return
  }
  const next = { ...basic.filters, natures: [...new Set([...basic.filters.natures, ...(value.natures || [])])],
    types: [...new Set([...basic.filters.types, ...(value.types || [])])],
    medals: [...new Set([...basic.filters.medals, ...(value.medals || [])])],
    marks: [...new Set([...basic.filters.marks, ...(value.marks || [])])], pool: [...new Set([...basic.filters.pool, ...(value.pool || [])])] }
  for (const key of ['shiny', 'colorful'] as const) if (value[key]) next[key] = true
  for (const key of ['gender', 'medal', 'speciality', 'acquisition', 'captured_days'] as const) if (value[key]) next[key] = value[key]
  if (value.search) next.search = value.search
  if ((value.level_min ?? 1) > 1 || (value.level_max ?? 60) < 60) { next.level_min = value.level_min ?? 1; next.level_max = Math.min(value.level_max ?? 60, 60) }
  basic.patch(next, false)
  const ranges: Partial<PetConditions> = { egg_groups: [...new Set([...advanced.filters.egg_groups, ...(value.egg_groups || [])])] }
  for (const [field] of measures) if (value[`${field}_min`] != null || value[`${field}_max`] != null) {
    ranges[`${field}_min`] = value[`${field}_min`] ?? null; ranges[`${field}_max`] = value[`${field}_max`] ?? null
  }
  // 两个 composable 各自取消防抖，只提交一次合并查询，保留当前池的 AND/OR。
  advanced.patch(ranges, false); props.reload()
}
defineExpose({ cancel: () => { settings.value = false; error.value = '' } })
</script>
<template>
  <section class="shortcut-section">
    <div class="quick-filter-head"><h3>快捷条件</h3><div class="button-row"><button class="text-button" :aria-expanded="settings" @click="settings = !settings">设置</button><button class="text-button" :disabled="saving" @click="save(defaultPetShortcuts)">重置</button></div></div>
    <div id="saved-shortcuts" class="quick-filters saved-shortcuts" aria-label="快捷条件"><button v-for="(item, index) in items" :key="index" class="chip" :title="item.name" :class="{ active: selected(item.filters) }" :aria-pressed="selected(item.filters)" @click="apply(item.filters)">{{ item.name }}</button></div>
    <p v-if="error && !settings" role="alert" class="filter-note">重置失败：{{ error }}</p>
  </section>
  <PetShortcutSettings v-if="settings" :items="items" :options="basic.options.value" :groups="advanced.groups.value" :saving="saving" :error="error" @close="settings = false; error = ''" @save="save"></PetShortcutSettings>
</template>
