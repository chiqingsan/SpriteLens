import type { NearbyCoverage } from '../types/nearby'
import type { WorldMapEntry } from '../types/worldMap'

/** 坐标统一保留 2 位小数：格网 path 会长期留在 DOM，避免浮点尾数把字符串撑大。 */
function round2(value: number) {
  return Math.round(value * 100) / 100
}

/**
 * 本次足迹格网 → 单条 SVG path。rows 每个 run 是同一行的连续格，直接合成一个矩形，
 * 比逐格画方块少一个数量级的子路径；矩形裁剪到地图图片范围，全部在界外时返回空串。
 * 足迹格表示本次连接里人物采样及其观察半径覆盖到的范围，不代表服务器 AOI。
 */
export function coveragePath(coverage: NearbyCoverage, map: WorldMapEntry): string {
  const { origin_x, origin_y, side } = map.projection
  const { width, height } = map.image
  if (!(side > 0) || !(width > 0) || !(height > 0)) return ''
  const scaleX = width / side
  const scaleY = height / side
  const cellWidth = coverage.cell_size * scaleX
  const cellHeight = coverage.cell_size * scaleY
  if (!(cellWidth > 0) || !(cellHeight > 0)) return ''
  // 世界格 (0,0) 的左上角在底图里的像素坐标；格索引与 origin 都允许为负。
  const gridLeft = -origin_x * scaleX
  const gridTop = -origin_y * scaleY
  const parts: string[] = []
  for (const [gy, gx, run] of coverage.rows) {
    if (run <= 0) continue
    const left = Math.max(0, gx * cellWidth + gridLeft)
    const top = Math.max(0, gy * cellHeight + gridTop)
    const right = Math.min(width, (gx + run) * cellWidth + gridLeft)
    const bottom = Math.min(height, (gy + 1) * cellHeight + gridTop)
    const x = round2(left)
    const y = round2(top)
    const w = round2(right - left)
    const h = round2(bottom - top)
    if (!(w > 0) || !(h > 0)) continue
    parts.push(`M${x.toFixed(2)},${y.toFixed(2)}h${w.toFixed(2)}v${h.toFixed(2)}h${(-w).toFixed(2)}z`)
  }
  return parts.join('')
}
