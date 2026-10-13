import { mount, flushPromises } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import PetShortcuts from './PetShortcuts.vue'
import { usePetFilters } from '../composables/usePetFilters'
import { usePetAdvancedFilters } from '../composables/usePetAdvancedFilters'
import { emptyRanges, parsePetConditions } from '../types/petConditions'
it('保存失败保留编辑并可重试，乐观预览不会使重试重复追加', async () => {
  const basic = usePetFilters(vi.fn(), vi.fn()), advanced = usePetAdvancedFilters(vi.fn(), vi.fn())
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value() { this.open = true } })
  basic.restore({ level_min: 60 })
  const applied = { search: '', level_min: 60, level_max: 60, gender: 0, natures: [], types: [], pool: [], pool_mode: 'and' as const, shiny: false, colorful: false, medal: 0, marks: [], speciality: 0, acquisition: 0, captured_days: 0, egg_groups: [], egg_mode: 'any' as const, ...emptyRanges() }
  const persist = vi.fn().mockRejectedValueOnce(new Error('合成保存失败')).mockResolvedValueOnce(undefined)
  const wrapper = mount(PetShortcuts, { props: { basic, advanced, applied, items: [], busy: () => false, persist, reload: vi.fn(), notify: vi.fn() }, global: { stubs: { teleport: true } } })
  try {
    await wrapper.get('.quick-filter-head .text-button').trigger('click')
    await wrapper.findAll('label').find(item => item.text() === '雌性')!.get('input').setValue(true)
    await wrapper.get('#btn-pin-filters').trigger('click')
    await wrapper.get('#shortcut-name').setValue('待保存条件')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('合成保存失败')
    expect(wrapper.get('form').attributes('hidden')).toBeUndefined()
    await wrapper.setProps({ items: [{ name: '待保存条件', filters: applied }] })
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(persist.mock.calls[1]![0]).toHaveLength(2)
    expect(persist.mock.calls[1]![0][0].filters).toEqual({ gender: 2 })
    expect(wrapper.find('form').exists()).toBe(false)
  } finally { wrapper.unmount(); document.body.innerHTML = '' }
})

it('自定义快捷条件追加且保留当前池模式，不清除已选条件', async () => {
  const basic = usePetFilters(vi.fn(), vi.fn()), advanced = usePetAdvancedFilters(vi.fn(), vi.fn()), reload = vi.fn()
  basic.patch({ shiny: true, natures: [1], pool_mode: 'or' }, false)
  advanced.patch({ egg_groups: ['植物组'], height_position_min: 10 }, false)
  const filters = parsePetConditions({ gender: 2, natures: [2], egg_groups: ['动物组'], shiny: false, pool_mode: 'and', talent_min: 4 })
  expect(filters).not.toHaveProperty('talent_min')
  const wrapper = mount(PetShortcuts, { props: { basic, advanced, applied: {}, items: [{ name: '追加条件', filters }], busy: () => false, persist: async () => {}, reload, notify: vi.fn() }, global: { stubs: { teleport: true } } })
  try {
    await wrapper.get('#saved-shortcuts .chip').trigger('click')
    expect(basic.filters).toMatchObject({ shiny: true, gender: 2, natures: [1, 2], pool_mode: 'or' })
    expect(advanced.filters).toMatchObject({ egg_groups: ['植物组', '动物组'], height_position_min: 10 })
    expect(reload).toHaveBeenCalledTimes(1)
    expect(basic.query()).not.toHaveProperty('talent_min')
    expect(wrapper.get('#saved-shortcuts .chip').attributes('aria-pressed')).toBe('true')
    await wrapper.get('#saved-shortcuts .chip').trigger('click')
    expect(basic.filters).toMatchObject({ shiny: true, gender: 0, natures: [1], pool_mode: 'or' })
    expect(advanced.filters).toMatchObject({ egg_groups: ['植物组'], height_position_min: 10 })
  } finally { wrapper.unmount() }
})

it('旧快捷和查询响应不恢复不可见的实际体型范围或满值预设', () => {
  const filters = parsePetConditions({ height_min: 1, height_max: 2, weight_min: 3, weight_max: 4,
    voice_min: -20, height_position_min: 25, pool: ['medal', 'max_height', 'max_weight'] })
  expect(filters).toEqual({ voice_min: -20, height_position_min: 25, pool: ['medal'] })
  const model = usePetAdvancedFilters(vi.fn(), vi.fn())
  model.restore(filters)
  expect(model.query()).not.toHaveProperty('height_min')
  expect(model.query()).not.toHaveProperty('weight_min')
  expect(model.query().height_position_min).toBe(25)
})
