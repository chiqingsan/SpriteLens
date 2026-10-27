import { describe, expect, it } from 'vitest'
import { parseWorldMaps, usableWorldMap, worldMapUnavailableReason } from './worldMap'

const catalog = parseWorldMaps({
  schema_version: 1,
  coordinate_version: 1,
  maps: {
    '10003': {
      name: '卡洛西亚大陆',
      availability: 'supported',
      image: { url: '/static/maps/10003.webp', width: 4096, height: 4096 },
      projection: { origin_x: 306000, origin_y: 408000, side: 408000 },
      calibration: { level: 'verified' },
    },
    '10018': {
      name: '魔法学院',
      availability: 'candidate',
      image: { url: '/static/maps/10018.webp', width: 4096, height: 4096 },
      projection: { origin_x: -886161, origin_y: -891000, side: 180000 },
      calibration: { level: 'candidate' },
    },
  },
})

describe('世界地图清单解析与可用性', () => {
  it('只放行 supported 且 verified 的地图', () => {
    expect(usableWorldMap(catalog, '10003')?.name).toBe('卡洛西亚大陆')
    expect(usableWorldMap(catalog, '10018')).toBeNull()
    expect(usableWorldMap(catalog, null)).toBeNull()
    expect(usableWorldMap(null, '10003')).toBeNull()
  })

  it('不可用原因按清单、资源、地图、支持等级、校准等级逐层给出', () => {
    expect(worldMapUnavailableReason(null, '10003')).toBe('地图清单尚未加载')
    expect(worldMapUnavailableReason(catalog, null)).toBe('等待场景资源信息')
    expect(worldMapUnavailableReason(catalog, '30001')).toBe('此场景暂无地图')
    expect(worldMapUnavailableReason(catalog, '10018')).toBe('此场景地图暂不可用')
    const unverified = parseWorldMaps({
      schema_version: 1,
      coordinate_version: 1,
      maps: { '10003': { ...catalog.maps['10003'], calibration: { level: 'candidate' } } },
    })
    expect(worldMapUnavailableReason(unverified, '10003')).toBe('此场景地图尚未校准')
    expect(worldMapUnavailableReason(catalog, '10003')).toBe('')
  })

  it('清单损坏时整块报错，不把半份地图当已校准资源', () => {
    expect(() => parseWorldMaps({ schema_version: 1, coordinate_version: 1, maps: { '10003': { ...catalog.maps['10003'], availability: 'ready' } } }))
      .toThrow('availability')
    expect(() => parseWorldMaps({ schema_version: 1, coordinate_version: 1, maps: { 'abc': catalog.maps['10003'] } }))
      .toThrow('地图编号必须是数字字符串')
    expect(() => parseWorldMaps({ schema_version: 1, coordinate_version: 1, maps: { '10003': { ...catalog.maps['10003'], image: { url: 'maps/10003.webp', width: 4096, height: 4096 } } } }))
      .toThrow('image')
  })
})
