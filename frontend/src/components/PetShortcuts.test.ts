import { mount, flushPromises } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import PetShortcuts from './PetShortcuts.vue'
import { usePetFilters } from '../composables/usePetFilters'
import { usePetAdvancedFilters } from '../composables/usePetAdvancedFilters'
import { defaultPetShortcuts, parsePetConditions, parsePetShortcuts } from '../types/petConditions'
it('快捷保存失败保留勾选并可重试，重置只恢复默认快捷项', async () => {
  const basic = usePetFilters(vi.fn(), vi.fn()), advanced = usePetAdvancedFilters(vi.fn(), vi.fn()), reload = vi.fn()
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value() { this.open = true } })
  basic.restore({ level_min: 60, gender: 1 })
  basic.options.value.medals = [{ id: 1001, name: '大块头' }]
  const persist = vi.fn().mockRejectedValueOnce(new Error('合成保存失败')).mockResolvedValue(undefined)
  const wrapper = mount(PetShortcuts, { props: { basic, advanced, applied: {}, items: defaultPetShortcuts, busy: () => false, persist, reload, notify: vi.fn() }, global: { stubs: { teleport: true } } })
  try {
    await wrapper.get('.quick-filter-head .text-button').trigger('click')
    expect((wrapper.findAll('label').find(item => item.text() === '大块头')!.get('input').element as HTMLInputElement).checked).toBe(true)
    await wrapper.findAll('label').find(item => item.text() === '雌性')!.get('input').setValue(true)
    // 弹窗底部是「取消 / 保存设置」，保存取最后一个按钮。
    await wrapper.get('footer button:last-child').trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('合成保存失败')
    await wrapper.get('footer button:last-child').trigger('click'); await flushPromises()
    expect(persist.mock.calls[1]![0]).toEqual([...defaultPetShortcuts, { name: '雌性', filters: { gender: 2 } }])
    expect(wrapper.find('dialog').exists()).toBe(false)
    await wrapper.findAll('.quick-filter-head .text-button')[1]!.trigger('click'); await flushPromises()
    expect(persist.mock.calls[2]![0]).toEqual(defaultPetShortcuts)
    expect(basic.filters).toMatchObject({ level_min: 60, gender: 1 })
    expect(reload).not.toHaveBeenCalled()
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
  expect(parsePetShortcuts([defaultPetShortcuts[0], { name: '奖牌 · 大块头', filters: { medal: 1001 } },
    { name: '系别 · 火', filters: { types: ['火'] } }])).toEqual([defaultPetShortcuts[0], { name: '火', filters: { types: ['火'] } }])
  const filters = parsePetConditions({ height_min: 1, height_max: 2, weight_min: 3, weight_max: 4,
    voice_min: -20, height_position_min: 25, pool: ['medal', 'max_height', 'max_weight'] })
  expect(filters).toEqual({ voice_min: -20, height_position_min: 25, pool: ['medal'] })
  const model = usePetAdvancedFilters(vi.fn(), vi.fn())
  model.restore(filters)
  expect(model.query()).not.toHaveProperty('height_min')
  expect(model.query()).not.toHaveProperty('weight_min')
  expect(model.query().height_position_min).toBe(25)
})
