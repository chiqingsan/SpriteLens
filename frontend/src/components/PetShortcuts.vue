<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import type { PetFilterModel } from '../composables/usePetFilters'
import { measures, type PetAdvancedModel } from '../composables/usePetAdvancedFilters'
import type { PetConditions, PetShortcut } from '../types/petConditions'
import PetShortcutSettings from './PetShortcutSettings.vue'
const props = defineProps<{ basic: PetFilterModel; advanced: PetAdvancedModel; applied: Partial<PetConditions>; items: PetShortcut[]; busy: () => boolean; persist: (items: PetShortcut[]) => Promise<void>; reload: () => void; notify: (message: string, bad: boolean) => void }>()
const settings = ref(false)
const defaultMarks = ['大块头', '小不点', '婉转声', '粗嗓门']
const name = ref(''), editor = ref(false), saving = ref(false), error = ref(''), input = ref<HTMLInputElement>()
let pending: Partial<PetConditions> | null = null
let baseItems: PetShortcut[] = []
const dirty = computed(() => props.busy() || !props.advanced.valid.value || Object.entries({ ...props.basic.query(), ...props.advanced.query() }).some(([key, value]) => {
  if (key === 'sort' || key === 'desc') return false
  const applied = props.applied[key as keyof PetConditions]
  if (typeof applied === 'boolean') return String(value) !== (applied ? '1' : '0')
  if (Array.isArray(applied)) return String(value).split(',').filter(Boolean).sort().join(',') !== applied.map(String).sort().join(',')
  return key === 'search' ? String(value).toLowerCase() !== applied : String(value) !== String(applied ?? '')
}))
async function pin(items: PetShortcut[]) {
  error.value = ''
  if (dirty.value) { props.notify('请等待筛选完成并确认输入有效', true); return }
  if (items.length >= 256) { props.notify('最多固定256组条件，请先移除一组', true); return }
  const f = props.applied, options = props.basic.options.value, tags: string[] = []
  for (const key of ['shiny', 'colorful'] as const) if (f[key]) tags.push(key === 'shiny' ? '异色' : '炫彩')
  for (const key of f.pool || []) tags.push({ medal: '有奖牌', male: '雄性', shiny: '异色', max_height: '满身高', max_weight: '满体重' }[key as 'medal'] || key)
  tags.push(...(f.marks || []))
  if (f.medal) tags.push('奖牌：' + (options.medals?.find(item => item.id === f.medal)?.name || f.medal))
  if (f.speciality) tags.push('特性：' + (options.specialities?.find(item => item.id === f.speciality)?.name || f.speciality))
  if (f.acquisition) tags.push('获取：' + (options.acquisitions?.find(item => item.id === f.acquisition)?.name || f.acquisition))
  if (f.captured_days) tags.push(`捕获：近${f.captured_days}天`)
  if (f.gender) tags.push(f.gender === 1 ? '雄性' : '雌性')
  if ((f.level_min ?? 1) > 1 || (f.level_max ?? 60) < 60) tags.push(`等级 ${f.level_min}–${f.level_max}`)
  for (const id of f.natures || []) tags.push('性格：' + (options.natures.find(item => item.id === id)?.name || id))
  for (const name of f.types || []) tags.push('系别：' + name)
  for (const name of f.egg_groups || []) tags.push('蛋组：' + name)
  for (const [field, label, unit] of measures) if (f[`${field}_min`] != null || f[`${field}_max`] != null) tags.push(`${label} ${f[`${field}_min`] ?? '不限'}–${f[`${field}_max`] ?? '不限'} ${unit}`)
  if (!tags.length && !f.search) { props.notify('请先选择要固定的筛选条件', true); return }
  baseItems = items.slice(); pending = JSON.parse(JSON.stringify(f)); name.value = (tags.join(' · ') || '搜索：' + f.search).slice(0, 40); editor.value = true
  await nextTick(); input.value?.focus()
}
async function save(items: PetShortcut[]) {
  saving.value = true; error.value = ''
  try { await props.persist(items); editor.value = false; settings.value = false; pending = null }
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
    for (const key of ['natures', 'types', 'marks', 'pool'] as const) {
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
defineExpose({ cancel: () => { settings.value = false; editor.value = false; pending = null; error.value = '' } })
</script>
<template>
  <section class="shortcut-section">
<div class="quick-filter-head"><h3>快捷条件</h3><div class="button-row"><button class="text-button" :aria-expanded="settings" @click="settings = !settings">设置</button><button class="text-button" @click="basic.patch({ marks: [] })">重置</button></div></div>
    <div class="quick-filters"><button v-for="label in defaultMarks" :key="label" class="chip" :class="{ active: basic.filters.marks.includes(label) }" :aria-pressed="basic.filters.marks.includes(label)" @click="basic.patch({ marks: basic.filters.marks.includes(label) ? basic.filters.marks.filter(item => item !== label) : [...basic.filters.marks, label] })">{{ label }}</button></div>
  </section>
  <div id="saved-shortcuts" class="saved-shortcuts" aria-label="已固定快捷条件"><div v-for="(item, index) in items" :key="index" class="saved-shortcut"><button class="chip" :title="item.name" :class="{ active: selected(item.filters) }" :aria-pressed="selected(item.filters)" @click="apply(item.filters)">{{ item.name }}</button></div></div>
  <PetShortcutSettings v-if="settings" :items="items" :options="basic.options.value" :groups="advanced.groups.value" :saving="saving" :error="error" @close="settings = false; editor = false; pending = null; error = ''" @pin="pin" @save="save">
    <form id="shortcut-editor" class="shortcut-editor" :hidden="!editor" @submit.prevent="pending && name.trim() && save(baseItems.concat([{ name: name.trim(), filters: pending }]))"><label class="field"><span>快捷条件名称</span><input id="shortcut-name" ref="input" v-model="name" maxlength="40" required autocomplete="off"></label><div class="button-row"><button type="submit" class="primary-button small" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button><button id="btn-cancel-shortcut" type="button" class="ghost-button small" :disabled="saving" @click="editor = false; pending = null">取消</button></div></form>
  </PetShortcutSettings>
</template>
