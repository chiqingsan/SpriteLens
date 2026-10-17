import { createApp, h, ref } from 'vue'
import BreedingPlannerPage from './pages/BreedingPlannerPage.vue'
import type { PlannerHost } from './composables/useBreedingPlanner'

export function mountBreedingPlanner(root: HTMLElement, host: PlannerHost) {
  const page = ref<InstanceType<typeof BreedingPlannerPage> | null>(null)
  const app = createApp({ render: () => h(BreedingPlannerPage, { ref: page, host }) })
  app.mount(root)
  return { load: () => page.value?.load(), pause: () => page.value?.pause(),
    resetAccount: () => page.value?.resetAccount(), unmount: () => app.unmount() }
}
