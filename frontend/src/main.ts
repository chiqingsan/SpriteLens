export { mountCaptureDiagnostics } from './captureDiagnosticsBridge'
import { createApp, h, ref } from 'vue'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { createApiClient } from './api/client'
import EggBoxPage from './pages/EggBoxPage.vue'
import type { EggBoxHost } from './composables/useEggBox'
import EggDexPage from './pages/EggDexPage.vue'
export { mountHome } from './homeBridge'
export { mountCollectionLines } from './collectionLinesBridge'
export { mountBreederLibrary } from './breederLibraryBridge'
export { mountBreedingPlanner } from './breedingPlannerBridge'
export { mountHandbook } from './handbookBridge'
export { mountColors } from './colorsBridge'
export { mountPetFilters } from './petFilterBridge'
export { mountPetInventory } from './petInventoryBridge'

export function mountEggBox(root: HTMLElement, host: EggBoxHost) {
  const page = ref<InstanceType<typeof EggBoxPage> | null>(null)
  const app = createApp({ render: () => h(EggBoxPage, { ref: page, host }) })
  app.mount(root)
  return {
    flush: () => page.value?.flush(),
    load: () => page.value?.load(),
    resume: (version: number) => page.value?.resume(version),
    pause: () => page.value?.pause(),
    resetAccount: () => page.value?.resetAccount(),
    unmount: () => app.unmount(),
  }
}

export function mount(root: HTMLElement, token: string) {
  const active = ref(true), api = createApiClient(token)
  const page = ref<InstanceType<typeof EggDexPage> | null>(null)
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: { setup: () => () => h(EggDexPage, { ref: page, api, active: active.value }) } },
  ] })
  const app = createApp({ render: () => h(RouterView) })
  app.use(createPinia()).use(router)
  void router.push('/')
  app.mount(root)
  return { pause: () => { active.value = false }, resume: () => { active.value = true },
    reveal: (key: string | number) => page.value?.reveal(key), unmount: () => app.unmount() }
}
