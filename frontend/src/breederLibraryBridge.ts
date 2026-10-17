import { createApp, h, ref } from 'vue'
import BreederLibraryPage from './pages/BreederLibraryPage.vue'
import type { BreederHost } from './composables/useBreederLibrary'

export function mountBreederLibrary(root: HTMLElement, host: BreederHost) {
  const page = ref<InstanceType<typeof BreederLibraryPage> | null>(null)
  const app = createApp({ render: () => h(BreederLibraryPage, { ref: page, host }) })
  app.mount(root)
  return { load: () => page.value?.load(), pause: () => page.value?.pause(),
    resetAccount: () => page.value?.resetAccount(), unmount: () => app.unmount() }
}
