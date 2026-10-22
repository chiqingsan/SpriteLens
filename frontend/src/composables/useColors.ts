import { computed, onScopeDispose, ref, shallowRef } from 'vue'
import type { ApiClient } from '../api/client'
import { matrixKey, parseColors, type ColorAxis, type ColorPet, type Colors, type ColorCell } from '../types/colors'

/** 三态格子：目录无卡 / 有卡无持有者 / 有持有者。 */
export type ColorCellState =
  | { state: 'empty' }
  | { state: 'card'; cell: ColorCell }
  | { state: 'pets'; pets: ColorPet[]; cell: ColorCell | null }
export interface ColorMatrixRow { mix: ColorAxis; cells: ColorCellState[] }

export function useColors(api: ApiClient) {
  const data = shallowRef<Colors | null>(null)
  const loading = ref(false)
  const error = ref('')
  let generation = 0
  let controller: AbortController | undefined
  let active = true, loaded = false

  function invalidate() {
    ++generation
    controller?.abort()
  }
  async function load() {
    if (!active) return
    invalidate()
    const current = generation
    controller = new AbortController()
    loading.value = true
    error.value = ''
    try {
      const response = await api('/api/colors', controller.signal)
      if (current === generation) { data.value = parseColors(response); loaded = true }
    } catch (err) {
      if (current === generation) error.value = err instanceof Error ? err.message : String(err)
    } finally {
      if (current === generation) loading.value = false
    }
  }
  function pause() { active = false; invalidate(); loading.value = false }
  function resume(force = false) {
    active = true
    if (force || !loaded) return load()
  }
  // 切号后残留的是上一账号的持有者，必须丢弃并等下次进入页面重取。
  function resetAccount() { pause(); data.value = null; error.value = ''; loaded = false }
  onScopeDispose(invalidate)

  // 矩阵按轴展开：cells 有键而 matrix 无键即「有卡但没抽到」。
  const matrixRows = computed<ColorMatrixRow[]>(() => {
    const colors = data.value
    if (!colors) return []
    return colors.mix_axis.map(mix => ({
      mix,
      cells: colors.base_axis.map(base => {
        const key = matrixKey(base.name, mix.name)
        const pets = colors.matrix[key]
        if (pets?.length) return { state: 'pets', pets, cell: colors.cells[key] || null }
        const cell = colors.cells[key]
        if (cell) return { state: 'card', cell }
        return { state: 'empty' }
      }),
    }))
  })
  // 收录卡数：矩阵内 + 赛季卡涉及的卡号去重（与既有口径一致）。
  const collected = computed(() => {
    const colors = data.value
    if (!colors) return 0
    const seen = new Set<string>()
    Object.values(colors.matrix).forEach(pets => pets.forEach(pet => seen.add(pet.card_id)))
    colors.seasonal.forEach(pet => seen.add(pet.card_id))
    return seen.size
  })
  const metaText = computed(() => data.value
    ? `收录 ${collected.value} / ${data.value.card_total} 张 · 持有者 ${data.value.pet_total} 只 · 赛季卡 ${data.value.seasonal.length} 只`
    : '底色在横轴、混色在纵轴；数据来自宠物帧的 glass 参数')

  return { data, loading, error, matrixRows, collected, metaText, load, pause, resume, resetAccount }
}
