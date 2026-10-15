export interface EggBoxRange {
  min: number
  max: number
}

export interface EggBoxMeasurementRanges {
  height_cm: EggBoxRange | null
  weight_g: EggBoxRange | null
}

export interface EggBoxEntry {
  instance_id: number
  egg_conf_id: number
  egg_name: string
  species_name: string
  description: string
  description_source: string
  icon_url: string
  fallback_icon_url: string
  egg_type_name: string
  egg_kind: 'regular' | 'special' | 'shiny' | 'colorful' | 'mystery' | 'unknown'
  egg_group_names: string[]
  hatch_label: string
  quantity: number
  obtained_at: number
  historical: boolean
  hatching: boolean
  hatch_known: boolean
  historical_hatching: boolean
  hatch_progress: number
  special_egg_conf_id: number
  height_cm: number
  weight_g: number
  measurement_ranges: EggBoxMeasurementRanges
}

export interface EggBox {
  eggs: EggBoxEntry[]
  total: number
  hatching: number | null
  historical_hatching: number
  source: 'unknown' | 'observed' | 'historical' | 'mixed'
  version: number
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function safeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value)
}

function string(value: unknown): value is string {
  return typeof value === 'string'
}

function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(string)
}

function isRange(value: unknown): value is EggBoxRange {
  return record(value) && finite(value.min) && finite(value.max) && value.max > value.min
}

function isRanges(value: unknown): value is EggBoxMeasurementRanges {
  return record(value)
    && (value.height_cm === null || isRange(value.height_cm))
    && (value.weight_g === null || isRange(value.weight_g))
}

function isSource(value: unknown): value is EggBox['source'] {
  return value === 'unknown' || value === 'observed' || value === 'historical' || value === 'mixed'
}

function isEntry(value: unknown): value is EggBoxEntry {
  if (!record(value)) return false
  return ['instance_id', 'egg_conf_id', 'quantity', 'obtained_at', 'special_egg_conf_id', 'height_cm', 'weight_g']
    .every(key => safeInteger(value[key]))
    && ['egg_name', 'species_name', 'description', 'description_source', 'icon_url', 'fallback_icon_url', 'egg_type_name', 'hatch_label']
      .every(key => string(value[key]))
    && typeof value.egg_kind === 'string' && ['regular', 'special', 'shiny', 'colorful', 'mystery', 'unknown'].includes(value.egg_kind)
    && strings(value.egg_group_names)
    && ['historical', 'hatching', 'hatch_known', 'historical_hatching']
      .every(key => typeof value[key] === 'boolean')
    && finite(value.hatch_progress) && value.hatch_progress >= 0 && value.hatch_progress <= 1
    && isRanges(value.measurement_ranges)
}

function isEggBox(value: unknown): value is EggBox {
  if (!record(value)) return false
  return Array.isArray(value.eggs) && value.eggs.every(isEntry)
    && ['total', 'historical_hatching', 'version'].every(key => safeInteger(value[key]))
    && (value.hatching === null || safeInteger(value.hatching))
    && isSource(value.source)
}

export function parseEggBox(value: unknown): EggBox {
  if (!isEggBox(value)) throw new Error('蛋仓数据格式不正确')
  return value
}
