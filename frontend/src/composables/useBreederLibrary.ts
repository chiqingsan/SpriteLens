import { computed, reactive, ref, shallowRef, watch } from 'vue'
import { parseBreederLibrary, type BreederLibrary, type BreederParent } from '../types/breederLibrary'

export interface BreederHost {
  load: (query: Record<string, string | number>) => Promise<unknown | null>
  cancel: () => void
  context: () => { uid: number | null; version: number; generation: number }
  openPet: (gid: string) => void
}
const defaults = () => ({ search: '', groups: [] as string[], natures: [] as string[], marks: [] as string[],
  voice_min: null as number | null, voice_max: null as number | null,
  height_min: null as number | null, height_max: null as number | null,
  weight_min: null as number | null, weight_max: null as number | null, same_nature: true })

export function useBreederLibrary(host: BreederHost) {
  const filters = reactive(defaults()), data = shallowRef<BreederLibrary | null>(null)
  const male = ref(''), female = ref(''), anchor = ref(0), malePage = ref(1), femalePage = ref(1)
  const loading = ref(false), error = ref('')
  let generation = 0, timer: ReturnType<typeof setTimeout> | undefined, active = false, committed = ''
  const invalidRange = computed(() => (['voice', 'height', 'weight'] as const).some(field => {
    const low = filters[`${field}_min`], high = filters[`${field}_max`], min = field === 'voice' ? -100 : 0
    return low !== null && (!Number.isFinite(low) || low < min || low > 100)
      || high !== null && (!Number.isFinite(high) || high < min || high > 100)
      || low !== null && high !== null && low > high
  }))
  function query(): Record<string, string | number> {
    const result: Record<string, string | number> = { search: filters.search, groups: filters.groups.join(','),
      natures: filters.natures.join(','), marks: filters.marks.join(','), same_nature: Number(filters.same_nature),
      male: male.value, female: female.value, anchor: anchor.value, male_page: malePage.value, female_page: femalePage.value }
    for (const field of ['voice', 'height', 'weight'] as const) for (const bound of ['min', 'max'] as const) {
      const key = `${field}_${bound}` as const, value = filters[key]
      result[key] = value === null ? '' : field === 'voice' ? value : value / 100
    }
    return result
  }
  function invalidate() { ++generation; clearTimeout(timer); host.cancel(); loading.value = false }
  async function load() {
    active = true
    if (invalidRange.value) return
    clearTimeout(timer)
    const params = query(), context = host.context(), signature = JSON.stringify([params, context])
    if (signature === committed && !error.value) return
    const current = ++generation
    loading.value = true; error.value = ''
    try {
      const payload = await host.load(params)
      const latest = host.context()
      if (current !== generation || payload === null || latest.uid !== context.uid || latest.generation !== context.generation) return
      const parsed = parseBreederLibrary(payload)
      if (parsed.uid !== context.uid || parsed.version < latest.version) return
      data.value = parsed; male.value = parsed.selected_male?.gid || ''; female.value = parsed.selected_female?.gid || ''
      anchor.value = parsed.anchor; malePage.value = parsed.male_page; femalePage.value = parsed.female_page
      committed = JSON.stringify([query(), { ...latest, version: parsed.version }])
    } catch (cause) {
      if (current === generation) error.value = cause instanceof Error ? cause.message : String(cause)
    } finally { if (current === generation) loading.value = false }
  }
  watch(filters, () => {
    invalidate(); malePage.value = 1; femalePage.value = 1
    if (active) timer = setTimeout(() => { void load() }, 180)
  }, { flush: 'sync' })
  watch(() => filters.same_nature, () => { male.value = ''; female.value = ''; anchor.value = 0 }, { flush: 'sync' })
  function select(parent: BreederParent) {
    invalidate()
    const selected = parent.gender === 1 ? male : female
    if (selected.value === parent.gid) {
      selected.value = ''
      if (anchor.value === parent.gender) { male.value = ''; female.value = ''; anchor.value = 0 }
    } else {
      selected.value = parent.gid
      if (!anchor.value) anchor.value = parent.gender
    }
    malePage.value = 1; femalePage.value = 1; void load()
  }
  function clearSelection() { invalidate(); male.value = ''; female.value = ''; anchor.value = 0; malePage.value = 1; femalePage.value = 1; void load() }
  function paginate(gender: number, page: number) { invalidate(); (gender === 1 ? malePage : femalePage).value = page; void load() }
  function pause() { active = false; invalidate() }
  function resetAccount() {
    pause(); data.value = null; committed = ''; error.value = ''; male.value = ''; female.value = ''; anchor.value = 0
    malePage.value = 1; femalePage.value = 1; Object.assign(filters, defaults())
  }
  function resetFilters() { Object.assign(filters, defaults()) }
  function range(field: 'voice' | 'height' | 'weight', bound: 'min' | 'max', value: number, commit: boolean) {
    const minimum = field === 'voice' ? -100 : 0
    const key = `${field}_${bound}` as const, other = `${field}_${bound === 'min' ? 'max' : 'min'}` as const
    filters[key] = bound === 'min' && value === minimum || bound === 'max' && value === 100 ? null : value
    if (bound === 'min' ? value > (filters[other] ?? 100) : value < (filters[other] ?? minimum)) {
      filters[other] = value === (bound === 'min' ? 100 : minimum) ? null : value
    }
    if (commit && active) void load()
  }
  return { filters, data, loading, error, invalidRange, male, female, anchor, load, select, clearSelection, paginate,
    pause, resetAccount, resetFilters, range, refresh: () => { committed = ''; void load() } }
}
