/** 世界地图清单 DTO：与 `data/static/world_maps.json` 的运行时子集一一对应。 */
export interface WorldMapImage {
  url: string
  width: number
  height: number
}
export interface WorldMapProjection {
  origin_x: number
  origin_y: number
  side: number
}
export interface WorldMapCalibration {
  level: 'verified' | 'candidate'
}
export interface WorldMapEntry {
  name: string
  availability: 'supported' | 'candidate'
  image: WorldMapImage
  projection: WorldMapProjection
  calibration: WorldMapCalibration
}
export interface WorldMapCatalog {
  schema_version: number
  coordinate_version: number
  maps: Record<string, WorldMapEntry>
}

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object'
}
function positiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) > 0
}

function parseEntry(mapId: string, value: unknown): WorldMapEntry {
  const label = `世界地图清单格式无效：${mapId}`
  if (!record(value)) throw Error(label)
  const image = value.image
  const projection = value.projection
  const calibration = value.calibration
  if (typeof value.name !== 'string' || !value.name) throw Error(`${label}.name`)
  if (value.availability !== 'supported' && value.availability !== 'candidate') throw Error(`${label}.availability`)
  if (!record(image) || typeof image.url !== 'string' || !image.url.startsWith('/static/')
    || !positiveInteger(image.width) || !positiveInteger(image.height)) throw Error(`${label}.image`)
  if (!record(projection) || !Number.isSafeInteger(projection.origin_x) || !Number.isSafeInteger(projection.origin_y)
    || !positiveInteger(projection.side)) throw Error(`${label}.projection`)
  if (!record(calibration) || (calibration.level !== 'verified' && calibration.level !== 'candidate')) {
    throw Error(`${label}.calibration`)
  }
  return {
    name: value.name,
    availability: value.availability,
    image: { url: image.url, width: image.width, height: image.height },
    projection: {
      origin_x: projection.origin_x as number,
      origin_y: projection.origin_y as number,
      side: projection.side,
    },
    calibration: { level: calibration.level },
  }
}

/** 严格校验接口返回值：清单损坏时整块不可用，不能把半份地图当已校准资源。 */
export function parseWorldMaps(value: unknown): WorldMapCatalog {
  if (!record(value) || !positiveInteger(value.schema_version) || !positiveInteger(value.coordinate_version)
    || !record(value.maps)) throw Error('世界地图清单格式无效')
  const maps: Record<string, WorldMapEntry> = {}
  for (const [mapId, entry] of Object.entries(value.maps)) {
    if (!/^\d+$/.test(mapId)) throw Error('世界地图清单格式无效：地图编号必须是数字字符串')
    maps[mapId] = parseEntry(mapId, entry)
  }
  return { schema_version: value.schema_version, coordinate_version: value.coordinate_version, maps }
}

/** 只有“支持且已现场校准”的地图才允许画正式点位；候选地图只展示不可用原因。 */
export function usableWorldMap(catalog: WorldMapCatalog | null, resourceId: string | null): WorldMapEntry | null {
  if (!catalog || !resourceId) return null
  const entry = catalog.maps[resourceId]
  if (!entry || entry.availability !== 'supported' || entry.calibration.level !== 'verified') return null
  return entry
}

/** 地图模式不可用时的用户可读原因；可用时返回空串。 */
export function worldMapUnavailableReason(catalog: WorldMapCatalog | null, resourceId: string | null): string {
  if (!catalog) return '地图清单尚未加载'
  if (!resourceId) return '等待场景资源信息'
  const entry = catalog.maps[resourceId]
  if (!entry) return '此场景暂无地图'
  if (entry.availability !== 'supported') return '此场景地图暂不可用'
  if (entry.calibration.level !== 'verified') return '此场景地图尚未校准'
  return ''
}
