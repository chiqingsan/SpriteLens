import { computed, ref } from 'vue'
import type { ApiClient } from '../api/client'
import { parsePetDetail, parsePets, type PetAccount, type PetView } from '../types/pets'

export function usePets(api: ApiClient, account: () => PetAccount, query: () => Record<string, string | number>,
  committed: () => void, failed: (message: string) => void) {
  const data = ref<ReturnType<typeof parsePets> | null>(null)
  const view = ref<PetView>('point'), page = ref(1), boxId = ref<number | null>(null), teams = ref(false)
  const selected = ref<number | null>(null), busy = ref(false), error = ref('')
  const detail = ref<ReturnType<typeof parsePetDetail> | null>(null), detailBusy = ref(false), detailError = ref('')
  const visible = ref(false)
  let sequence = 0, active = false, controller: AbortController | undefined
  let detailSequence = 0, detailController: AbortController | undefined
  let loadedQuery = ''
  function queryKey() {
    const params = new URLSearchParams()
    Object.entries(query()).forEach(([key, value]) => { if (value !== '') params.set(key, String(value)) })
    return params.toString()
  }
  function invalidate() { sequence++; controller?.abort(); controller = undefined }
  function invalidateDetail() { detailSequence++; detailController?.abort(); detailController = undefined; detailBusy.value = false }
  const boxes = computed(() => (data.value?.backpack.boxes || []).filter(box => box.slots.some(slot => slot.state !== 'empty')))
  const box = computed(() => boxes.value.find(item => item.box_id === boxId.value))
  const pets = computed(() => data.value?.pets || [])
  const pages = computed(() => Math.max(1, Math.ceil(pets.value.length / 30)))
  const cards = computed(() => pets.value.slice((page.value - 1) * 30, page.value * 30))
  const slots = computed(() => teams.value ? (data.value?.backpack.teams || []).flatMap(team => team.slots) : box.value?.slots || [])
  const byGid = computed(() => new Map(pets.value.map(pet => [pet.gid, pet])))
  // 自定义排序视图：当前页宠物占前部槽位，末页剩余位置复用箱位的空槽展示。
  const cardSlots = computed(() => [
    ...cards.value.map(pet => ({ gid: pet.gid, state: 'matched' as const })),
    ...(cards.value.length
      ? Array.from({ length: 30 - cards.value.length }, () => ({ gid: 0, state: 'empty' as const }))
      : []),
  ])
  function commit(payload: ReturnType<typeof parsePets>, key = queryKey()) {
    if (data.value && (data.value.uid !== payload.uid || data.value.version !== payload.version)) {
      invalidateDetail()
      detail.value = null
      detailError.value = ''
    }
    data.value = payload; error.value = ''; loadedQuery = key
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
      const key = queryKey(), params = new URLSearchParams(key)
      params.set('options_version', data.value?.uid === owner.uid ? String(data.value.version) : '-1')
      const response = await api('/api/pets?' + params, controller.signal)
      if (!current()) return
      const payload = response && typeof response === 'object' && !Array.isArray(response)
        && !('options' in response) && data.value?.uid === owner.uid
        ? { ...response, options: data.value.options } : response
      const parsed = parsePets(payload)
      if (parsed.uid !== owner.uid || parsed.version < account().version) return
      busy.value = false; commit(parsed, key)
      // 主动筛选后带用户到命中箱；实时推送刷新仍保留正在阅读的箱。
      if (resetPage && parsed.backpack.filtering && !teams.value && box.value?.matched === 0) {
        boxId.value = boxes.value.find(item => item.matched)?.box_id ?? boxId.value
      }
    } catch (cause) {
      if (!current()) return
      busy.value = false; error.value = cause instanceof Error ? cause.message : String(cause); failed(error.value)
    } finally { if (ticket === sequence) busy.value = false }
  }
  async function resume() {
    active = true; visible.value = true
    const owner = account()
    if (!data.value || data.value.uid !== owner.uid || data.value.version < owner.version
      || loadedQuery !== queryKey() || error.value) await load(false)
  }
  async function loadDetail(gid: number) {
    const owner = account()
    const snapshot = data.value
    if (!snapshot || snapshot.uid !== owner.uid || !snapshot.pets.some(pet => pet.gid === gid)) return
    if (detail.value?.gid === gid && detail.value.version === snapshot.version && detail.value.uid === snapshot.uid) return
    invalidateDetail()
    detail.value = null
    detailError.value = ''
    const ticket = detailSequence
    const snapshotVersion = snapshot.version
    const request = new AbortController()
    detailController = request
    detailBusy.value = true
    const current = () => active && ticket === detailSequence && selected.value === gid
      && owner.uid === account().uid && owner.generation === account().generation
      && data.value?.uid === snapshot.uid && data.value.version === snapshotVersion
    try {
      const query = new URLSearchParams({ uid: String(snapshot.uid), version: String(snapshotVersion) })
      const response = parsePetDetail(await api(`/api/pets/${gid}?${query}`, request.signal))
      if (!current()) return
      if (response.uid !== snapshot.uid || response.version < snapshotVersion || response.gid !== gid) {
        detailError.value = '精灵数据已更新，请重新打开详情'
        return
      }
      detail.value = response
    } catch (cause) {
      if (!current() || cause instanceof DOMException && cause.name === 'AbortError') return
      detailError.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      if (ticket === detailSequence) {
        detailBusy.value = false
        detailController = undefined
      }
    }
  }
  function resetAccount() {
    invalidate(); invalidateDetail(); busy.value = false; data.value = null; detail.value = null; detailError.value = ''
    selected.value = null; boxId.value = null; teams.value = false; page.value = 1; error.value = ''
  }
  return { data, view, page, boxId, teams, selected, busy, error, visible, boxes, box, pets, pages, cards, cardSlots, slots, byGid,
    detail, detailBusy, detailError, loadDetail,
    load, resume, accept, invalidate, resetAccount,
    activate: () => { active = true; visible.value = true }, pause: () => { active = false; visible.value = false; invalidate(); invalidateDetail(); busy.value = false },
    setBox: (id: number) => { teams.value = id === 0; if (id) boxId.value = id },
    setView: (value: PetView) => { view.value = value; page.value = 1 },
    find: (gid: number) => byGid.value.get(gid) || null }
}
export type PetsModel = ReturnType<typeof usePets>
