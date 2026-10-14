import { computed, ref } from 'vue'
import type { ApiClient } from '../api/client'
import { parsePets, type PetAccount, type PetView } from '../types/pets'

export function usePets(api: ApiClient, account: () => PetAccount, query: () => Record<string, string | number>,
  committed: () => void, failed: (message: string) => void) {
  const data = ref<ReturnType<typeof parsePets> | null>(null)
  const view = ref<PetView>('point'), page = ref(1), boxId = ref<number | null>(null), teams = ref(false)
  const selected = ref<number | null>(null), busy = ref(false), error = ref('')
  const visible = ref(false)
  let sequence = 0, active = false, controller: AbortController | undefined
  function invalidate() { sequence++; controller?.abort(); controller = undefined }
  const boxes = computed(() => (data.value?.backpack.boxes || []).filter(box => box.slots.some(slot => slot.state !== 'empty')))
  const box = computed(() => boxes.value.find(item => item.box_id === boxId.value))
  const pets = computed(() => data.value?.pets || [])
  const pages = computed(() => Math.max(1, Math.ceil(pets.value.length / 30)))
  const cards = computed(() => pets.value.slice((page.value - 1) * 30, page.value * 30))
  const slots = computed(() => teams.value ? (data.value?.backpack.teams || []).flatMap(team => team.slots) : box.value?.slots || [])
  const byGid = computed(() => new Map(pets.value.map(pet => [pet.gid, pet])))
  // 自定义排序视图：把当前页宠物包成全 matched 槽位，复用箱位卡片渲染与键盘导航，无中间空位。
  const cardSlots = computed(() => cards.value.map(pet => ({ gid: pet.gid, state: 'matched' as const })))
  function commit(payload: ReturnType<typeof parsePets>) {
    data.value = payload; error.value = ''
    if (!box.value) boxId.value = (boxes.value.find(item => item.matched) || boxes.value[0])?.box_id ?? null
    page.value = Math.min(page.value, pages.value)
    if (selected.value !== null && !byGid.value.has(selected.value)) selected.value = null
    committed()
  }
  function accept(value: unknown) {
    const payload = parsePets(value), owner = account()
    if (payload.uid !== owner.uid || payload.version < owner.version) throw new Error('宠物快照账号或版本与当前状态不一致')
    commit(payload)
  }
  async function load(resetPage = true) {
    invalidate()
    if (resetPage) page.value = 1
    const ticket = sequence, owner = account()
    controller = new AbortController(); busy.value = true; error.value = ''
    const current = () => active && ticket === sequence && owner.generation === account().generation
    try {
      const params = new URLSearchParams()
      Object.entries(query()).forEach(([key, value]) => { if (value !== '') params.set(key, String(value)) })
      const payload = await api('/api/pets?' + params, controller.signal)
      if (!current()) return
      const parsed = parsePets(payload)
      if (parsed.uid !== owner.uid || parsed.version < account().version) return
      busy.value = false; commit(parsed)
      // 主动筛选后带用户到命中箱；实时推送刷新仍保留正在阅读的箱。
      if (resetPage && parsed.backpack.filtering && !teams.value && box.value?.matched === 0) {
        boxId.value = boxes.value.find(item => item.matched)?.box_id ?? boxId.value
      }
    } catch (cause) {
      if (!current()) return
      busy.value = false; error.value = cause instanceof Error ? cause.message : String(cause); failed(error.value)
    } finally { if (ticket === sequence) busy.value = false }
  }
  function resetAccount() { invalidate(); busy.value = false; data.value = null; selected.value = null; boxId.value = null; teams.value = false; page.value = 1; error.value = '' }
  return { data, view, page, boxId, teams, selected, busy, error, visible, boxes, box, pets, pages, cards, cardSlots, slots, byGid,
    load, accept, invalidate, resetAccount,
    activate: () => { active = true; visible.value = true }, pause: () => { active = false; visible.value = false; invalidate(); busy.value = false },
    setBox: (id: number) => { teams.value = id === 0; if (id) boxId.value = id },
    setView: (value: PetView) => { view.value = value; page.value = 1 },
    find: (gid: number) => byGid.value.get(gid) || null }
}
export type PetsModel = ReturnType<typeof usePets>
