import { createApp, h, ref } from 'vue'
import NearbyPage from './pages/NearbyPage.vue'
import type { NearbyHost } from './composables/useNearby'
import FloatingRadar from './pages/FloatingRadar.vue'
export function mountFloatingRadar(root: HTMLElement, channel: BroadcastChannel, host: { close: () => Promise<unknown>; setOpacity: (percent: number) => Promise<unknown> }) {
  const app = createApp({ render: () => h(FloatingRadar, { channel, host }) })
  app.mount(root)
  return { unmount: () => app.unmount() }
}
export function mountNearby(root: HTMLElement, host: NearbyHost) {
  const page = ref<InstanceType<typeof NearbyPage> | null>(null)
  const app = createApp({ render: () => h(NearbyPage, { ref: page, host }) })
  app.mount(root)
  return { update: (summary: unknown) => page.value?.update(summary), load: () => page.value?.load(),
    pause: () => page.value?.pause(), resume: () => page.value?.resume(), unmount: () => app.unmount() }
}
