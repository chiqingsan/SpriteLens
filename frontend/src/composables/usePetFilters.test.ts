import { initialMeasurementLimits } from '../types/petFilters'
import { afterEach, expect, it, vi } from 'vitest'
import { usePetFilters } from './usePetFilters'

afterEach(() => { vi.useRealTimers() })

it('输入防抖合并，离页、切号和恢复取消未提交的输入', () => {
  vi.useFakeTimers()
  const reload = vi.fn()
  const invalidate = vi.fn()
  const model = usePetFilters(reload, invalidate)
  model.activate()
  model.search('迪'); model.search('迪莫')
  expect(invalidate).toHaveBeenCalledTimes(2)
  vi.advanceTimersByTime(219)
  expect(reload).not.toHaveBeenCalled()
  vi.advanceTimersByTime(1)
  expect(reload).toHaveBeenCalledTimes(1)
  model.search('旧搜索'); model.pause(); vi.runAllTimers()
  expect(reload).toHaveBeenCalledTimes(1)
  model.activate(); model.search('切号前'); model.resetAccount(); vi.runAllTimers()
  expect(reload).toHaveBeenCalledTimes(1)
  model.search('恢复前'); model.restore({ search: '快捷条件' }); vi.runAllTimers()
  expect(model.query().search).toBe('快捷条件')
  expect(reload).toHaveBeenCalledTimes(1)
})

it('上下限保持一致，恢复不保留旧条件或共享数组，账号选项清除', () => {
  const model = usePetFilters(vi.fn(), vi.fn())
  model.level('min', 80); model.level('max', 40)
  expect([model.filters.level_min, model.filters.level_max]).toEqual([40, 40])
  const natures = [1, 2]
  model.restore({ search: ' A ', natures, types: ['火'], desc: true, sort: 'level' })
  natures.push(3)
  expect(model.query()).toMatchObject({ search: 'A', natures: '1,2', types: '火', desc: '1', sort: 'level' })
  model.restore({ search: '下一条件' })
  expect(model.query()).toMatchObject({ natures: '', types: '', desc: '', sort: 'dex_no' })
  const shortcut = { search: '基础与扩展组合', egg_groups: ['动物组'], height_min: 1, talent_min: 4 }
  model.restore(shortcut)
  expect(model.query()).not.toHaveProperty('egg_groups')
  expect(model.query()).not.toHaveProperty('height_min')
  expect(model.query()).not.toHaveProperty('talent_min')
  model.updateOptions({ natures: [{ id: 1, name: '性格' }], types: ['火'], talent_max: 6, measurement_limits: initialMeasurementLimits,
    sorts: [{ key: 'gid', label: '编号' }] })
  model.nature(1); model.type('火')
  model.resetAccount()
  expect(model.options.value.natures).toEqual([])
  expect(model.options.value.types).toEqual([])
  expect(model.query()).toMatchObject({ natures: '', types: '' })
})

it('选项契约失败可见，不能用错误响应替换已有选项', () => {
  const model = usePetFilters(vi.fn(), vi.fn())
  const options = { natures: [], types: [], sorts: [{ key: 'gid', label: '编号' }], talent_max: 4, measurement_limits: initialMeasurementLimits }
  model.updateOptions(options)
  expect(() => model.updateOptions({ ...options, talent_max: '4' })).toThrow('格式不正确')
  expect(model.options.value.talent_max).toBe(4)
})
