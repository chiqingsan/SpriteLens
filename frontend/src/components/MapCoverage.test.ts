import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MapCoverage from './MapCoverage.vue'
import type { NearbyCoverage } from '../types/nearby'
import type { WorldMapEntry } from '../types/worldMap'

vi.mock('../domain/mapCoverage', () => ({ coveragePath: vi.fn((coverage: NearbyCoverage) => JSON.stringify(coverage.rows)) }))
import { coveragePath } from '../domain/mapCoverage'

const map: WorldMapEntry = { name: '测试', availability: 'supported', image: { url: '', width: 100, height: 100 }, projection: { origin_x: 0, origin_y: 0, side: 1000 }, calibration: { level: 'verified' } }
const coverage = (rows: [number, number, number][], uid = '1'): NearbyCoverage => ({ uid, map_id: '1', layer: 'visit', scope: 'session', revision: 1, cell_size: 10, cells: rows.length, rows })

describe('覆盖路径缓存', () => {
  it('相同行复用；重置后版本号重复、账号或地图改变时重新计算', async () => {
    vi.mocked(coveragePath).mockClear()
    const wrapper = mount(MapCoverage, { props: { map, coverage: coverage([[1, 1, 1]]) } })
    await wrapper.setProps({ coverage: coverage([[1, 1, 1]]) })
    expect(coveragePath).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ coverage: coverage([[1, 2, 1]]) })
    expect(coveragePath).toHaveBeenCalledTimes(2)
    await wrapper.setProps({ coverage: coverage([[1, 2, 1]], '2') })
    await wrapper.setProps({ map: { ...map, projection: { ...map.projection, side: 2000 } } })
    expect(coveragePath).toHaveBeenCalledTimes(4)
    await wrapper.setProps({ coverage: null })
    expect(wrapper.find('.map-coverage').exists()).toBe(false)
    await wrapper.setProps({ coverage: coverage([[1, 2, 1]], '2') })
    expect(coveragePath).toHaveBeenCalledTimes(5)
  })
})
