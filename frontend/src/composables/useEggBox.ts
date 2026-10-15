import { computed, onScopeDispose, reactive, ref, shallowRef, watch } from 'vue'
import { parseEggBox, type EggBox, type EggBoxEntry } from '../types/eggBox'

export interface EggBoxHost {
  load: () => Promise<unknown>
  cancel: () => void
  versionChanged: (version: number) => void
}

export function useEggBox(host: EggBoxHost) {
  const data = shallowRef<EggBox | null>(null)
  const loading = ref(false)
  const error = ref('')
  const selectedId = ref<number | null>(null)
  const filters = reactive({ search: '', category: 'all', ascending: false })
  let generation = 0

  const categories = computed(() => {
    const eggs = data.value?.eggs || []
    return [
      { id: 'all', label: '全部', count: eggs.length },
      ...[
        { id: 'regular', label: '普通蛋' }, { id: 'special', label: '特殊蛋' },
        { id: 'shiny', label: '异色蛋' }, { id: 'colorful', label: '炫彩蛋' },
        { id: 'mystery', label: '神奇蛋' }, { id: 'unknown', label: '未收录分类' },
      ].filter(category => category.id !== 'unknown' || eggs.some(egg => egg.egg_kind === 'unknown'))
        .map(category => ({ ...category, count: eggs.filter(egg => egg.egg_kind === category.id).length })),
    ]
  })

  const visibleEggs = computed(() => {
    const keyword = filters.search.trim().toLocaleLowerCase()
    return [...(data.value?.eggs || [])]
      .filter(egg => {
        if (filters.category !== 'all' && egg.egg_kind !== filters.category) return false
        if (!keyword) return true
        return [egg.egg_name, egg.species_name, String(egg.instance_id), String(egg.egg_conf_id)]
          .some(value => value.toLocaleLowerCase().includes(keyword))
      })
      .sort((a, b) => {
        const byTime = a.obtained_at - b.obtained_at
        const byId = a.instance_id - b.instance_id
        return (filters.ascending ? 1 : -1) * (byTime || byId)
      })
  })

  const selected = computed(() => visibleEggs.value.find(egg => egg.instance_id === selectedId.value) || null)

  watch(visibleEggs, eggs => {
    if (!eggs.some(egg => egg.instance_id === selectedId.value)) selectedId.value = eggs[0]?.instance_id ?? null
  })

  async function load() {
    const current = ++generation
    loading.value = true
    error.value = ''
    try {
      const next = parseEggBox(await host.load())
      if (current !== generation) return
      data.value = next
      host.versionChanged(next.version)
      if (!visibleEggs.value.some(egg => egg.instance_id === selectedId.value)) {
        selectedId.value = visibleEggs.value[0]?.instance_id ?? null
      }
    } catch (cause) {
      if (current === generation) error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      if (current === generation) loading.value = false
    }
  }

  function invalidate() {
    ++generation
    host.cancel()
    loading.value = false
  }

  function pause() {
    invalidate()
  }

  function resetAccount() {
    pause()
    data.value = null
    selectedId.value = null
    filters.category = 'all'
    error.value = ''
  }

  function select(egg: EggBoxEntry) {
    selectedId.value = egg.instance_id
  }

  function moveSelection(offset: number) {
    const eggs = visibleEggs.value
    if (!eggs.length) return
    const current = eggs.findIndex(egg => egg.instance_id === selectedId.value)
    const next = (Math.max(current, 0) + offset + eggs.length) % eggs.length
    selectedId.value = eggs[next].instance_id
  }

  function clearSelection() {
    selectedId.value = null
  }

  onScopeDispose(pause)
  return { data, loading, error, filters, categories, visibleEggs, selected, selectedId,
    load, pause, resetAccount, select, moveSelection, clearSelection }
}
