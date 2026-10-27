import { describe, expect, it } from 'vitest'
import { coveragePath } from './mapCoverage'
import type { NearbyCoverage } from '../types/nearby'
import type { WorldMapEntry } from '../types/worldMap'

// 1000 像素 ≈ 2000 原始单位，cell_size=100 → 每格 50 像素；(0,0) 格左上角在像素 -50,-50。
const MAP: WorldMapEntry = {
  name: '测试图',
  availability: 'supported',
  image: { url: '', width: 1000, height: 1000 },
  projection: { origin_x: 100, origin_y: 100, side: 2000 },
  calibration: { level: 'candidate' },
}
const coverage = (rows: [number, number, number][], cells = rows.reduce((sum, row) => sum + row[2], 0)): NearbyCoverage => ({
  uid: '1', map_id: '10003', layer: 'visit', scope: 'session', revision: 1, cell_size: 100, cells, rows,
})

describe('本次足迹格网路径', () => {
  it('每个 run 合并成一个矩形，坐标保留 2 位小数', () => {
    expect(coveragePath(coverage([[1, 0, 2], [2, 5, 3]]), MAP))
      .toBe('M0.00,0.00h50.00v50.00h-50.00zM200.00,50.00h150.00v50.00h-150.00z')
  })

  it('按图片边界裁剪：左/右越界裁到视口内，完全在界外的跳过', () => {
    // gx=0 时左边界在 -50，被裁到 0。
    expect(coveragePath(coverage([[1, 0, 2]]), MAP)).toBe('M0.00,0.00h50.00v50.00h-50.00z')
    // gx=19 run=3 右边界 1050，被裁到 1000。
    expect(coveragePath(coverage([[1, 19, 3]]), MAP)).toBe('M900.00,0.00h100.00v50.00h-100.00z')
    // gy=0 整行贴着上边界（裁剪后高度为 0），gy=40 在图片下方，均不生成矩形。
    expect(coveragePath(coverage([[0, 0, 2], [40, 0, 1]]), MAP)).toBe('')
    // 负格索引：gx=-3 的格完全在左侧界外，gx=40 的格完全在右侧界外。
    expect(coveragePath(coverage([[1, -3, 1], [1, 40, 2]]), MAP)).toBe('')
  })

  it('空 rows 返回空串', () => {
    expect(coveragePath(coverage([], 0), MAP)).toBe('')
  })

  it('投影或图片尺寸异常时返回空串而不抛错', () => {
    expect(coveragePath(coverage([[1, 0, 1]]), { ...MAP, projection: { ...MAP.projection, side: 0 } })).toBe('')
    expect(coveragePath(coverage([[1, 0, 1]]), { ...MAP, image: { url: '', width: 0, height: 1000 } })).toBe('')
  })
})
