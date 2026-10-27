import { ref, watch } from 'vue'

/* 图鉴类页面的显示偏好：网格 / 列表、舒适 / 紧凑。
   写进 localStorage 让选择跨会话保留；隐私模式下读写失败时静默退回默认值。 */
export type DexView = 'grid' | 'list'
export type DexDensity = 'comfortable' | 'compact'

const VIEW_KEY = 'spritelens.dex.view'
const DENSITY_KEY = 'spritelens.dex.density'

function readChoice<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try {
    const value = localStorage.getItem(key)
    return allowed.includes(value as T) ? (value as T) : fallback
  } catch { return fallback }
}

function writeChoice(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* 隐私模式 / 禁用存储时忽略 */ }
}

export function useDexDisplay() {
  const view = ref<DexView>(readChoice(VIEW_KEY, 'grid', ['grid', 'list'] as const))
  const density = ref<DexDensity>(readChoice(DENSITY_KEY, 'comfortable', ['comfortable', 'compact'] as const))
  watch(view, value => writeChoice(VIEW_KEY, value))
  watch(density, value => writeChoice(DENSITY_KEY, value))
  return { view, density }
}
