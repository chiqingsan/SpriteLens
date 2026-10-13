import { createApp, h, ref } from 'vue'
import PetFiltersPanel from './components/PetFiltersPanel.vue'
import { usePetFilters, type PetFilterBridge } from './composables/usePetFilters'
import { usePetAdvancedFilters } from './composables/usePetAdvancedFilters'
import { parsePetShortcuts, type PetShortcut, type PetConditions } from './types/petConditions'
export interface PetFilterHost { busy: () => boolean; persist: (items: PetShortcut[]) => Promise<void>; notify: (message: string, bad: boolean) => void }

export function mountPetFilters(root: HTMLElement, reload: () => void, invalidate: () => void, host: PetFilterHost): PetFilterBridge {
  const model = usePetFilters(reload, invalidate)
  const advanced = usePetAdvancedFilters(reload, invalidate)
  const applied = ref<Partial<PetConditions>>({}), items = ref<PetShortcut[]>([])
  const panel = ref<InstanceType<typeof PetFiltersPanel>>()
  function reset() { model.reset(); advanced.reset() }
  const app = createApp({ render: () => h(PetFiltersPanel, { ref: panel, basic: model, advanced, applied: applied.value, items: items.value,
    ...host, reload, reset: () => { reset(); reload() } }) })
  app.mount(root)
  return { query: () => ({ ...model.query(), ...advanced.query() }), restore: value => { model.restore(value); advanced.restore(value) }, reset,
    resetAccount: () => { model.resetAccount(); advanced.resetAccount(); applied.value = {}; panel.value!.cancel() },
    updateOptions: model.updateOptions, setFixed: value => { model.fixed.value = value },
    activate: () => { model.activate(); advanced.activate() }, pause: () => { model.pause(); advanced.pause() }, search: value => model.patch({ search: value }, false),
    patch: model.patch, toggleMaxed: model.toggleMaxed,
    sync: value => { model.updateOptions(value.options); advanced.groups.value = value.options.egg_groups; applied.value = value.filters },
    setShortcuts: value => { items.value = parsePetShortcuts(value) },
    unmount: () => { model.pause(); advanced.pause(); app.unmount() } }
}
