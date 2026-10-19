import { createApp, h, ref, watchEffect } from 'vue'
import { createApiClient } from './api/client'
import ColorsPage from './pages/ColorsPage.vue'

export interface ColorsHost {
  failed?: (message: string) => void
}

/** 色卡页挂载：与图鉴页同构，外壳只给根节点与 token，页面状态归 Vue。 */
export function mountColors(root: HTMLElement, token: string, host: ColorsHost = {}) {
  const page = ref<InstanceType<typeof ColorsPage> | null>(null)
  const ready = ref(false)
  const api = createApiClient(token)
  const app = createApp({ render: () => h(ColorsPage, { ref: page, api, active: ready.value }) })
  app.mount(root)
  // 外壳挂载即代表进入色卡页：active 由 false 翻到 true 触发首次加载。
  ready.value = true
  const stop = watchEffect(() => { if (page.value?.error) host.failed?.(page.value.error) })
  return {
    load: () => page.value?.load(), resume: () => page.value?.resume(), pause: () => page.value?.pause(),
    resetAccount: () => page.value?.resetAccount(), unmount: () => { stop(); app.unmount() },
  }
}
