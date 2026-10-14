export interface PetFilters {
  search: string; level_min: number; level_max: number; natures: number[]; types: string[]
  gender: number; sort: string; desc: boolean
  pool: string[]; pool_mode: 'and' | 'or'; shiny: boolean; colorful: boolean
  medal: number; medals: number[]; marks: string[]; speciality: number; acquisition: number; captured_days: number
}
export interface PetFilterOptions {
  natures: { id: number; name: string }[]; types: string[]
  sorts: { key: string; label: string }[]; talent_max: number
  medals?: { id: number; name: string }[]; specialities?: { id: number; name: string }[]
  acquisitions?: { id: number; name: string }[]
  type_icons?: Record<string, string>
  measurement_limits: PetMeasurementLimits
}
export type PetMeasurementLimits = Record<'height' | 'weight' | 'voice', { min: number; max: number }>
export const initialMeasurementLimits: PetMeasurementLimits = { height: { min: 0, max: 1 }, weight: { min: 0, max: 1 }, voice: { min: -100, max: 100 } }

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
export function parsePetFilterOptions(value: unknown): PetFilterOptions {
  if (!record(value) || !Array.isArray(value.natures) || !value.natures.every(item =>
    record(item) && Number.isSafeInteger(item.id) && typeof item.name === 'string')
    || !Array.isArray(value.types) || !value.types.every(item => typeof item === 'string')
    || !Array.isArray(value.sorts) || !value.sorts.every(item => record(item)
      && typeof item.key === 'string' && typeof item.label === 'string')
    || typeof value.talent_max !== 'number' || !Number.isSafeInteger(value.talent_max) || value.talent_max < 0) {
    throw new Error('宠物筛选选项格式不正确')
  }
  for (const key of ['medals', 'specialities', 'acquisitions']) {
    if (value[key] !== undefined && (!Array.isArray(value[key]) || !value[key].every(item => record(item) && Number.isSafeInteger(item.id) && typeof item.name === 'string'))) throw new Error('宠物筛选选项格式不正确')
  }
  const limits = value.measurement_limits
  if (value.type_icons !== undefined && (!record(value.type_icons) || Object.values(value.type_icons).some(url => typeof url !== 'string'))) throw new Error('系别图标格式不正确')
  if (!record(limits) || ['height', 'weight', 'voice'].some(key => {
    const range = limits[key]
    return !record(range) || typeof range.min !== 'number' || typeof range.max !== 'number'
      || !Number.isFinite(range.min) || !Number.isFinite(range.max) || range.min >= range.max || key !== 'voice' && range.min < 0
  })) throw new Error('宠物滑动条量程格式不正确')
  return { natures: value.natures.map(item => ({ id: Number(item.id), name: String(item.name) })),
    types: [...value.types], type_icons: (value.type_icons || {}) as Record<string, string>, sorts: value.sorts.map(item => ({ key: String(item.key), label: String(item.label) })),
    talent_max: value.talent_max,
    measurement_limits: limits as PetMeasurementLimits,
    acquisitions: (value.acquisitions || []) as { id: number; name: string }[],
    medals: (value.medals || []) as { id: number; name: string }[], specialities: (value.specialities || []) as { id: number; name: string }[] }
}
