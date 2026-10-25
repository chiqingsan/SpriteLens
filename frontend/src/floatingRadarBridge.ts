import { createApp, h } from 'vue'
import FloatingRadar from './pages/FloatingRadar.vue'

export type FloatingRadarHost = {
  close: () => Promise<unknown>
  setOpacity: (percent: number) => Promise<unknown>
}

/** 拖出雷达窗口的独立挂载点：只依赖雷达页与共享组件，不引入其他业务页（PERF04）。 */
export function mountFloatingRadar(root: HTMLElement, channel: BroadcastChannel, host: FloatingRadarHost) {
  const app = createApp({ render: () => h(FloatingRadar, { channel, host }) })
  app.mount(root)
  return { unmount: () => app.unmount() }
}
