import { reactive, ref } from 'vue'
import { initialMeasurementLimits, parsePetFilterOptions, type PetFilters, type PetFilterOptions } from '../types/petFilters'

function defaults(): PetFilters {
  return { search: '', level_min: 1, level_max: 60, natures: [], types: [],
    gender: 0, sort: 'dex_no', desc: false,
    pool: [], pool_mode: 'and', shiny: false, colorful: false, medal: 0, marks: [], speciality: 0, acquisition: 0, captured_days: 0 }
}

// 迁移期间唯一持有基础筛选状态；旧页只通过查询/命令接口使用，不保存副本。
export function usePetFilters(reload: () => void, invalidate: () => void) {
  const filters = reactive(defaults())
  const options = ref<PetFilterOptions>({ natures: [], types: [], sorts: [], talent_max: 0, measurement_limits: initialMeasurementLimits })
  const fixed = ref(false)
  let active = false
  let timer: ReturnType<typeof setTimeout> | undefined
  function cancel() { clearTimeout(timer); timer = undefined }
  function changed(delay = 0) {
    cancel()
    if (!active) return
    invalidate()
    if (delay) timer = setTimeout(() => { timer = undefined; reload() }, delay)
    else reload()
  }
  function search(value: string) { filters.search = value; changed(220) }
  function level(bound: 'min' | 'max', value: number) {
    value = Math.max(1, Math.min(60, value))
    if (bound === 'min') {
      filters.level_min = value; filters.level_max = Math.max(value, filters.level_max)
    } else {
      filters.level_max = value; filters.level_min = Math.min(value, filters.level_min)
    }
    changed(180)
  }
  function nature(id: number) {
    filters.natures = filters.natures.includes(id) ? filters.natures.filter(value => value !== id) : [...filters.natures, id]
    changed()
  }
  function type(name: string) {
    filters.types = filters.types.includes(name) ? filters.types.filter(value => value !== name) : [...filters.types, name]
    changed()
  }
  function restore(value: Partial<PetFilters>) {
    cancel()
    // 快捷条件还含蛋组/体型等原生切片的字段，不能把它们复制进 Vue 状态。
    Object.assign(filters, { search: value.search ?? '', level_min: Math.max(1, Math.min(value.level_min ?? 1, 60)),
      level_max: Math.min(value.level_max ?? 60, 60), natures: [...(value.natures || [])], types: [...(value.types || [])],
      gender: value.gender ?? 0, sort: value.sort ?? 'dex_no', desc: value.desc ?? false,
      pool: [...(value.pool || [])], pool_mode: value.pool_mode ?? 'and', shiny: value.shiny ?? false,
      colorful: value.colorful ?? false, medal: value.medal ?? 0, marks: [...(value.marks || [])], speciality: value.speciality ?? 0, acquisition: value.acquisition ?? 0, captured_days: value.captured_days ?? 0 })
  }
  function patch(value: Partial<PetFilters>, notify = true) {
    cancel(); Object.assign(filters, value)
    if (notify) changed()
  }
  function resetAccount() {
    cancel(); filters.natures = []; filters.types = []
    options.value = { ...options.value, natures: [], types: [], talent_max: 0, measurement_limits: initialMeasurementLimits }
    filters.medal = 0; filters.speciality = 0; options.value.medals = []; options.value.specialities = []
  }
  function toggleMaxed() {
    const enabled = filters.level_min === 60 && filters.level_max === 60
    filters.level_min = enabled ? 1 : 60; filters.level_max = 60; changed()
  }
  return { filters, options, fixed, search, level, nature, type, changed, toggleMaxed,
    query: () => ({ ...filters, search: filters.search.trim(), natures: filters.natures.join(','),
      types: filters.types.join(','), desc: filters.desc ? '1' : '', pool: filters.pool.join(','), marks: filters.marks.join(','),
      shiny: filters.shiny ? '1' : '0', colorful: filters.colorful ? '1' : '0' }),
    restore, patch, reset: () => restore(defaults()), resetAccount,
    updateOptions: (value: unknown) => {
      const parsed = parsePetFilterOptions(value)
      const medals = [1001, 1002, 1026, 1025, 1029, 1005, 1010, 1006, 1030, 1028]
      parsed.medals = parsed.medals?.filter(item => medals.includes(item.id)).sort((a, b) => medals.indexOf(a.id) - medals.indexOf(b.id))
      options.value = parsed
    },
    activate: () => { active = true }, pause: () => { active = false; cancel(); invalidate() } }
}
export type PetFilterModel = ReturnType<typeof usePetFilters>
export interface PetFilterBridge {
  query: () => Record<string, string | number>; restore: (value: Partial<PetFilters> & Partial<import('./usePetAdvancedFilters').AdvancedFilters & import('./usePetAdvancedFilters').PetRanges>) => void; reset: () => void
  resetAccount: () => void; updateOptions: (value: unknown) => void
  setFixed: (value: boolean) => void; activate: () => void; pause: () => void
  search: (value: string) => void; patch: PetFilterModel['patch']; toggleMaxed: () => void; unmount: () => void
  sync: (value: import('../types/pets').Pets) => void; setShortcuts: (value: unknown) => void
}
