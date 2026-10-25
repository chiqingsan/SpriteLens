import { createApp, h, ref } from 'vue'
import NearbyPage from './pages/NearbyPage.vue'
import type { NearbyHost } from './composables/useNearby'

// 雷达挂在独立入口（src/radar.ts）里，这里保留同名导出，主窗口壳的旧引用继续可用。
export { mountFloatingRadar } from './floatingRadarBridge'

export function mountNearby(root: HTMLElement, host: NearbyHost) {
  const page = ref<InstanceType<typeof NearbyPage> | null>(null)
  const app = createApp({ render: () => h(NearbyPage, { ref: page, host }) })
  app.mount(root)
  return { update: (summary: unknown) => page.value?.update(summary), load: () => page.value?.load(),
    pause: () => page.value?.pause(), resume: () => page.value?.resume(), unmount: () => app.unmount() }
}
