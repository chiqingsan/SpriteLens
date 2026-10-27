import { describe, expect, it } from 'vitest'
import { containsRaw, projectRaw, unprojectPixels } from './mapProjection'

const IMAGE = { width: 4096, height: 4096 }
const PROJECTION = { origin_x: 306000, origin_y: 408000, side: 408000 }

describe('原始坐标到地图像素的投影', () => {
  it('原点投到左上角，对角投到右下角', () => {
    expect(projectRaw(PROJECTION, IMAGE, 306000, 408000)).toEqual({ x: 0, y: 0 })
    expect(projectRaw(PROJECTION, IMAGE, 714000, 816000)).toEqual({ x: 4096, y: 4096 })
  })

  it('负原点的地图同样按同一公式换算', () => {
    const projection = { origin_x: -886161, origin_y: -891000, side: 180000 }
    expect(projectRaw(projection, IMAGE, -886161 + 90000, -891000 + 90000)).toEqual({ x: 2048, y: 2048 })
  })

  it('缺坐标或参数异常时返回 null，不猜位置', () => {
    expect(projectRaw(PROJECTION, IMAGE, null, 0)).toBeNull()
    expect(projectRaw(PROJECTION, IMAGE, 0, null)).toBeNull()
    expect(projectRaw({ ...PROJECTION, side: 0 }, IMAGE, 400000, 500000)).toBeNull()
    expect(projectRaw(PROJECTION, { width: 0, height: 0 }, 400000, 500000)).toBeNull()
  })

  it('反算是正变换的逆运算', () => {
    const point = projectRaw(PROJECTION, IMAGE, 426850, 661780)
    expect(point).not.toBeNull()
    const raw = unprojectPixels(PROJECTION, IMAGE, point!.x, point!.y)
    expect(raw!.x).toBeCloseTo(426850, 6)
    expect(raw!.y).toBeCloseTo(661780, 6)
  })

  it('覆盖范围含边界，越界坐标直接判否', () => {
    expect(containsRaw(PROJECTION, 306000, 408000)).toBe(true)
    expect(containsRaw(PROJECTION, 714000, 816000)).toBe(true)
    expect(containsRaw(PROJECTION, 305999, 408000)).toBe(false)
    expect(containsRaw(PROJECTION, 306000, 816001)).toBe(false)
    expect(containsRaw({ origin_x: -886161, origin_y: -891000, side: 180000 }, -886161, -891000)).toBe(true)
  })
})
