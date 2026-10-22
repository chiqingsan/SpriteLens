export interface EggBoxRange {
  min: number
  max: number
}

export interface EggBoxMeasurementRanges {
  height_cm: EggBoxRange | null
  weight_g: EggBoxRange | null
}

export type EggNest = '' | 'normal' | 'green'
export type EggBoxVoiceTag = '' | '婉转声' | '满分' | '粗嗓门' | '底分'
export interface EggBoxAnnotations {
  nature_id: number
  nest_override: EggNest
  note: string
  voice_tag: EggBoxVoiceTag
  voice_db: number | null
}
export interface EggBoxTags { nature: string; weight: string | null; voice: string | null; medals: string[]; nest: string }
export interface EggBoxSaveAnnotations extends EggBoxAnnotations { uid: number; instance_id: number }

export interface EggBoxEntry {
  instance_id: number
  egg_conf_id: number
  egg_name: string
  species_name: string
  chain_names: string[]
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
  favorite: boolean
  hatch_progress: number
  special_egg_conf_id: number
  height_cm: number
  weight_g: number
  home_egg: boolean
  annotations: EggBoxAnnotations
  tags: EggBoxTags
  measurement_ranges: EggBoxMeasurementRanges
}

export interface EggBox {
  eggs: EggBoxEntry[]
  uid: number
  total: number
  hatching: number | null
  historical_hatching: number
  source: 'unknown' | 'observed' | 'historical' | 'mixed'
  version: number
  nature_options: { id: number; name: string }[]
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

function isAnnotations(value: unknown): value is EggBoxAnnotations {
  return record(value) && safeInteger(value.nature_id) && value.nature_id >= 0
    && (value.nest_override === '' || value.nest_override === 'normal' || value.nest_override === 'green')
    && string(value.note)
    && (value.voice_tag === '' || value.voice_tag === '婉转声' || value.voice_tag === '满分'
      || value.voice_tag === '粗嗓门' || value.voice_tag === '底分')
    && (value.voice_db === null || safeInteger(value.voice_db) && value.voice_db >= -100 && value.voice_db <= 100)
}

function isTags(value: unknown): value is EggBoxTags {
  return record(value) && string(value.nature) && (value.weight === null || string(value.weight))
    && (value.voice === null || string(value.voice)) && strings(value.medals) && string(value.nest)
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
    && strings(value.chain_names)
    && typeof value.egg_kind === 'string' && ['regular', 'special', 'shiny', 'colorful', 'mystery', 'unknown'].includes(value.egg_kind)
    && strings(value.egg_group_names)
    && ['historical', 'hatching', 'hatch_known', 'historical_hatching']
      .every(key => typeof value[key] === 'boolean')
    && typeof value.favorite === 'boolean'
    && typeof value.home_egg === 'boolean' && isAnnotations(value.annotations)
    && isTags(value.tags)
    && finite(value.hatch_progress) && value.hatch_progress >= 0 && value.hatch_progress <= 1
    && isRanges(value.measurement_ranges)
}

function isEggBox(value: unknown): value is EggBox {
  if (!record(value)) return false
  return Array.isArray(value.eggs) && value.eggs.every(isEntry)
    && ['uid', 'total', 'historical_hatching', 'version'].every(key => safeInteger(value[key]))
    && (value.hatching === null || safeInteger(value.hatching))
    && Array.isArray(value.nature_options) && value.nature_options.every(item => record(item) && safeInteger(item.id) && string(item.name))
    && isSource(value.source)
}

export function parseEggBox(value: unknown): EggBox {
  if (!isEggBox(value)) throw new Error('蛋仓数据格式不正确')
  return value
}
