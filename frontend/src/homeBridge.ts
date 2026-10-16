import { createApp, h, ref } from 'vue'
import HomePage from './pages/HomePage.vue'
import type { HomeHost } from './composables/useHome'

export function mountHome(root: HTMLElement, host: HomeHost) {
  const page = ref<InstanceType<typeof HomePage> | null>(null)
  const app = createApp({ render: () => h(HomePage, { ref: page, host }) })
  app.mount(root)
  return {
    load: () => page.value?.load(),
    resume: (version: number) => page.value?.resume(version),
    pause: () => page.value?.pause(),
    resetAccount: () => page.value?.resetAccount(),
    unmount: () => app.unmount(),
  }
}
