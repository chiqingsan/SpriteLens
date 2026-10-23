import { createApp, h, ref } from 'vue'
import CaptureDiagnostics from './components/CaptureDiagnostics.vue'
import type { CaptureDiagnosticsHost } from './types/captureDiagnostics'
export function mountCaptureDiagnostics(root: HTMLElement, host: CaptureDiagnosticsHost) {
  const page = ref<InstanceType<typeof CaptureDiagnostics> | null>(null)
  const app = createApp({ render: () => h(CaptureDiagnostics, { ref: page, host }) })
  app.mount(root)
  return { update: (payload: unknown) => page.value?.update(payload), unmount: () => app.unmount() }
}
