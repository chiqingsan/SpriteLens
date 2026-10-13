import { computed, reactive, ref } from 'vue'
import { measures, emptyRanges, type RangeKey, type AdvancedFilters, type PetRanges } from '../types/petConditions'
export { measures } from '../types/petConditions'
export type { RangeKey, AdvancedFilters, PetRanges } from '../types/petConditions'
export function usePetAdvancedFilters(reload: () => void, invalidate: () => void) {
  const filters = reactive<AdvancedFilters & PetRanges>({ egg_groups: [], egg_mode: 'any', ...emptyRanges() })
  const invalid = reactive<Record<string, boolean>>({}), status = ref(''), groups = ref<string[]>([])
  const valid = computed(() => !Object.values(invalid).some(Boolean))
  let active = false, timer: ReturnType<typeof setTimeout> | undefined
  function cancel() { clearTimeout(timer); timer = undefined }
  function changed(delay = 0) {
    cancel(); invalidate()
    if (!active || !valid.value) return
    if (delay) timer = setTimeout(reload, delay)
    else reload()
  }
  function input(key: RangeKey, element: HTMLInputElement, commit = false) {
    const value = element.value === '' ? null : Number(element.value)
    invalid[key] = element.validity.badInput || value !== null && (!Number.isFinite(value) || !key.startsWith('voice') && value < 0 || key.includes('_position_') && value > 100)
    status.value = valid.value ? '' : '请输入有效范围：体型不能为负，范围位置为 0–100%。'
    filters[key] = value
    if (commit && valid.value) {
      const field = key.replace(/_(min|max)$/, '') as typeof measures[number][0]
      const low = filters[`${field}_min`], high = filters[`${field}_max`]
      if (low !== null && high !== null && low > high) {
        filters[`${field}_min`] = high; filters[`${field}_max`] = low; status.value = '已交换上下限。'
      }
    }
    changed(commit ? 0 : 220)
  }
  function restore(value: Partial<AdvancedFilters & PetRanges>) {
    cancel(); Object.keys(invalid).forEach(key => { delete invalid[key] }); status.value = ''
    Object.assign(filters, { egg_groups: [...(value.egg_groups || [])], egg_mode: value.egg_mode || 'any', ...emptyRanges() })
    measures.forEach(([field]) => { for (const bound of ['min', 'max'] as const) filters[`${field}_${bound}`] = value[`${field}_${bound}`] ?? null })
  }
  function patch(value: Partial<AdvancedFilters & PetRanges>, notify = true) {
    cancel(); Object.assign(filters, value)
    Object.keys(value).forEach(key => { if (key.endsWith('_min') || key.endsWith('_max')) delete invalid[key] })
    if (valid.value) status.value = ''
    if (notify) changed()
  }
  function range(field: typeof measures[number][0], bound: 'min' | 'max', value: number, minimum: number, maximum: number, commit: boolean) {
    const key = `${field}_${bound}` as RangeKey, other = `${field}_${bound === 'min' ? 'max' : 'min'}` as RangeKey
    filters[key] = bound === 'min' && value === minimum || bound === 'max' && value === maximum ? null : value
    if (filters[key] !== null && filters[other] !== null && (bound === 'min' ? value > filters[other]! : value < filters[other]!)) filters[other] = value
    delete invalid[key]; delete invalid[other]
    status.value = valid.value ? '' : status.value
    changed(commit ? 0 : 220)
  }
  return { filters, invalid, status, valid, groups, input, changed, restore, patch, range,
    group: (name: string) => { filters.egg_groups = filters.egg_groups.includes(name) ? filters.egg_groups.filter(item => item !== name) : [...filters.egg_groups, name]; changed() },
    clearRange: (field: typeof measures[number][0]) => { filters[`${field}_min`] = null; filters[`${field}_max`] = null; invalid[`${field}_min`] = false; invalid[`${field}_max`] = false; if (valid.value) status.value = ''; changed() },
    preset: (value: number) => { const next = filters.voice_min === value && filters.voice_max === value ? null : value; filters.voice_min = next; filters.voice_max = next; invalid.voice_min = false; invalid.voice_max = false; status.value = ''; changed() },
    query: (): Record<string, string | number> => { if (!valid.value) throw new Error(status.value); return Object.fromEntries(Object.entries(filters).map(([key, value]) => [key, Array.isArray(value) ? value.join(',') : value ?? ''])) },
    reset: () => restore({}), resetAccount: () => { restore({}); groups.value = [] },
    activate: () => { active = true }, pause: () => { active = false; cancel() } }
}
export type PetAdvancedModel = ReturnType<typeof usePetAdvancedFilters>
