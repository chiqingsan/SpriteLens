import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { createApiClient } from './api/client'
import EggDexPage from './pages/EggDexPage.vue'
export { mountPetFilters } from './petFilterBridge'
export { mountPetInventory } from './petInventoryBridge'

export function mount(root: HTMLElement, token: string): () => void {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: EggDexPage, props: { api: createApiClient(token) } },
  ] })
  const app = createApp({ render: () => h(RouterView) })
  app.use(createPinia()).use(router)
  void router.push('/')
  app.mount(root)
  return () => app.unmount()
}
