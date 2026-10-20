import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import PetMeasurementRow from './PetMeasurementRow.vue'

describe('精灵详情范围进度条', () => {
  it('显示实际范围的填充条和当前位置标记', () => {
    const wrapper = mount(PetMeasurementRow, {
      props: {
        field: 'height',
        measurement: { value: 1.59, limits: [1.37, 1.59], ratio: 1, status: 'within' },
        limits: [1.37, 1.59],
        referenceOnly: false,
      },
    })
    expect(wrapper.get('.detail-range-track').attributes('role')).toBe('progressbar')
    expect(wrapper.get('.detail-range-fill').attributes('style')).toContain('width: 100%')
    expect(wrapper.get('.detail-range-track > b').attributes('style')).toContain('left: 100%')
  })

  it('蛋蛋参考范围不伪造当前精灵进度', () => {
    const wrapper = mount(PetMeasurementRow, {
      props: {
        field: 'height',
        measurement: { value: 1.59, limits: [1.37, 1.59], ratio: 1, status: 'within' },
        limits: [1.2, 1.8],
        referenceOnly: true,
      },
    })
    expect(wrapper.find('.detail-range-fill').exists()).toBe(false)
    expect(wrapper.find('.detail-range-track > b').exists()).toBe(false)
    expect(wrapper.find('.detail-range-track').attributes('role')).toBeUndefined()
  })
})
