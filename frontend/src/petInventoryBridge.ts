import { createApp, h, nextTick, ref, watch } from 'vue'
import { createApiClient } from './api/client'
import { usePets } from './composables/usePets'
import PetInventory from './components/PetInventory.vue'
import type { PetAccount, PetView, Pets } from './types/pets'

export interface PetInventoryHost {
  account: () => PetAccount; query: () => Record<string, string | number>
  committed: (data: Pets) => void; failed: (message: string) => void
  view: (value: PetView) => void; reset: () => void; fixed: (value: boolean) => void
  imageMode: () => string
}
export function mountPetInventory(root: HTMLElement, token: string, host: PetInventoryHost) {
  const model = usePets(createApiClient(token), host.account, host.query,
    () => { void nextTick(() => { if (model.data.value) host.committed(model.data.value) }) }, host.failed)
  const inventory = ref<InstanceType<typeof PetInventory> | null>(null)
  const app = createApp({ render: () => h(PetInventory, { ref: inventory, model, imageMode: host.imageMode,
    onView: host.view, onReset: host.reset }) })
  app.mount(root)
  const stop = watch(model.view, value => host.fixed(value === 'point'), { immediate: true, flush: 'sync' })
  return { load: model.load, resume: model.resume, seed: model.accept, find: model.find, payload: () => model.data.value,
    selected: () => model.selected.value, isBusy: () => model.busy.value,
    selectGid: (gid: number) => inventory.value!.selectGid(gid),
    closeDetail: (preserve = false) => inventory.value!.closeDetail(preserve), openDetail: () => inventory.value!.openDetail(),
    setView: model.setView, setBox: (id: number) => inventory.value!.setBox(id), invalidate: model.invalidate,
    resetAccount: model.resetAccount, activate: model.activate, pause: () => { inventory.value!.saveScroll(); model.pause() },
    restoreScroll: () => inventory.value!.restoreScroll(),
    refreshPresentation: () => { model.data.value = model.data.value ? { ...model.data.value } : null },
    unmount: () => { model.pause(); stop(); app.unmount() } }
}
