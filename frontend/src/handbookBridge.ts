import { createApp, h, ref, watchEffect } from 'vue'
import HandbookPage from './pages/HandbookPage.vue'
import { createApiClient } from './api/client'

export interface HandbookHost {
  failed?: (message: string) => void
  notify?: (message: string) => void
}

/** 图鉴页挂载：外壳只在首次进入图鉴时调用，之后用返回的控制器切页。 */
export function mountHandbook(root: HTMLElement, token: string, host: HandbookHost = {}) {
  const api = createApiClient(token)
  const page = ref<InstanceType<typeof HandbookPage> | null>(null)
  const ready = ref(false)
  const app = createApp({ render: () => h(HandbookPage, { ref: page, api, active: ready.value }) })
  app.mount(root)
  // 外壳挂载即代表进入图鉴页：active 由 false 翻到 true 触发首次加载。
  ready.value = true
  const stop = watchEffect(() => { if (page.value?.error) host.failed?.(page.value.error) })
  return {
    load: () => page.value?.resume(),
    pause: () => page.value?.pause(),
    resume: () => page.value?.resume(),
    resetAccount: () => page.value?.resetAccount(),
    unmount: () => { stop(); app.unmount() },
  }
}
