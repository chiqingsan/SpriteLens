/** 纯画布投影：原始游戏坐标 ↔ 世界地图图片像素，不依赖 DOM。 */
export interface MapImageSize {
  width: number
  height: number
}
export interface MapProjection {
  origin_x: number
  origin_y: number
  side: number
}
export interface MapPoint {
  x: number
  y: number
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

/** 原始坐标映射到 4096 底图像素；缺坐标或参数异常时返回 null，不猜位置。 */
export function projectRaw(projection: MapProjection, image: MapImageSize, x: number | null, y: number | null): MapPoint | null {
  if (!finite(x) || !finite(y) || !finite(projection.origin_x) || !finite(projection.origin_y)
    || !finite(projection.side) || projection.side <= 0 || !finite(image.width) || !finite(image.height) || image.width <= 0 || image.height <= 0) {
    return null
  }
  return {
    x: (x - projection.origin_x) / projection.side * image.width,
    y: (y - projection.origin_y) / projection.side * image.height,
  }
}

/** 底图像素反算原始坐标，供点击命中与调试对照；逆变换与 projectRaw 使用同一组参数。 */
export function unprojectPixels(projection: MapProjection, image: MapImageSize, x: number, y: number): MapPoint | null {
  if (!finite(x) || !finite(y) || !finite(projection.origin_x) || !finite(projection.origin_y)
    || !finite(projection.side) || projection.side <= 0 || !finite(image.width) || !finite(image.height) || image.width <= 0 || image.height <= 0) {
    return null
  }
  return {
    x: x / image.width * projection.side + projection.origin_x,
    y: y / image.height * projection.side + projection.origin_y,
  }
}

/** 判断原始坐标是否落在这张地图的覆盖范围内（含边界）。 */
export function containsRaw(projection: MapProjection, x: number | null, y: number | null): boolean {
  if (!finite(x) || !finite(y)) return false
  return x >= projection.origin_x && x <= projection.origin_x + projection.side
    && y >= projection.origin_y && y <= projection.origin_y + projection.side
}
