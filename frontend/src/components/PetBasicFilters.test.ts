import { initialMeasurementLimits } from '../types/petFilters'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { expect, it, vi } from 'vitest'
import { mountPetFilters } from '../petFilterBridge'
import { usePetFilters } from '../composables/usePetFilters'
import PetBasicFilters from './PetBasicFilters.vue'

const options = { natures: Array.from({ length: 10 }, (_, index) => ({ id: index + 1, name: `性格 ${index}` })),
  types: ['火'], sorts: [{ key: 'gid', label: '编号' }, { key: 'level', label: '等级' }], talent_max: 4, measurement_limits: initialMeasurementLimits }

it('选项更新保留按钮和焦点，全部性格、排序与安全插值', async () => {
  document.body.innerHTML = '<div id="pet-search-controls"></div>'
  const model = usePetFilters(vi.fn(), vi.fn())
  model.activate(); model.updateOptions({ ...options, natures: [{ id: 1, name: '<img onerror=alert(1)>' }, ...options.natures.slice(1)] })
  const wrapper = mount(PetBasicFilters, { props: { model }, attachTo: document.body })
  try {
    const chip = wrapper.get('[data-nature="1"]')
    expect(chip.find('img').exists()).toBe(false)
    ;(chip.element as HTMLElement).focus()
    await chip.trigger('click')
    expect(chip.attributes('aria-pressed')).toBe('true')
    model.updateOptions(options); await nextTick()
    expect(wrapper.get('[data-nature="1"]').element).toBe(chip.element)
    expect(document.activeElement).toBe(chip.element)
    expect(wrapper.get('[data-nature="10"]').attributes('hidden')).toBeUndefined()
    model.fixed.value = true; await nextTick()
    expect((document.getElementById('f-sort') as HTMLSelectElement).disabled).toBe(true)
  } finally { wrapper.unmount(); model.pause(); document.body.innerHTML = '' }
})

it('卸载清理防抖和 Teleport，重新挂载只有一套控件', async () => {
  vi.useFakeTimers()
  document.body.innerHTML = '<div id="pet-search-controls"></div><div id="pet-filter-actions"></div><div id="root"></div>'
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
