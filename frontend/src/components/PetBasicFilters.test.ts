import { nextTick } from 'vue'
import { expect, it, vi } from 'vitest'
import { mountPetFilters } from '../petFilterBridge'

it('卸载清理防抖和 Teleport，重新挂载只有一套控件', async () => {
  vi.useFakeTimers()
  document.body.innerHTML = '<div id="pet-search-controls"></div><div id="pet-sort-root"></div><div id="pet-filter-actions"></div><div id="root"></div>'
  const reload = vi.fn()
  const host = { busy: () => false, persist: async () => {}, notify: vi.fn() }
  const bridge = mountPetFilters(document.getElementById('root')!, reload, vi.fn(), host)
  try {
    bridge.activate()
    const input = document.getElementById('f-search') as HTMLInputElement
    input.value = '未提交'; input.dispatchEvent(new Event('input', { bubbles: true }))
    bridge.unmount(); vi.runAllTimers()
    expect(reload).not.toHaveBeenCalled()
    expect(document.getElementById('f-search')).toBeNull()
    const second = mountPetFilters(document.getElementById('root')!, reload, vi.fn(), host)
    await nextTick()
    expect(document.querySelectorAll('#f-search')).toHaveLength(1)
    expect(second.query().search).toBe('')
    second.unmount()
  } finally { vi.useRealTimers(); document.body.innerHTML = '' }
})
