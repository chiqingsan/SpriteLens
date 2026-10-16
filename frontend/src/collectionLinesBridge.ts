import { createApp, h, ref } from 'vue'
import CollectionLinesPage from './pages/CollectionLinesPage.vue'
import type { CollectionHost } from './composables/useCollectionLines'

export function mountCollectionLines(root: HTMLElement, host: CollectionHost) {
  const page = ref<InstanceType<typeof CollectionLinesPage> | null>(null)
  const app = createApp({ render: () => h(CollectionLinesPage, { ref: page, host }) })
  app.mount(root)
  return {
    load: () => page.value?.load(), pause: () => page.value?.pause(),
    resetAccount: () => page.value?.resetAccount(), unmount: () => app.unmount(),
  }
}
