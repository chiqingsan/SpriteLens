export interface BreederParent {
  gid: string; name: string; species: string; dex_no: number; gender: 1 | 2; nature: string
  groups: string[]; marks: Array<{ label: string; name: string; source: 'worn' | 'reference' }>
  voice: number | null; height_ratio: number | null; weight_ratio: number | null
  is_shiny: boolean; is_colorful: boolean; icon_url: string
  location: { box_id: number; slot: number; row: number; column: number } | null
}
export interface BreederPrediction {
  groups: string[]; natures: Record<string, number>; random_percent: number; unknown_percent: number
  voice: number | null; height_ratio: number | null; weight_ratio: number | null
  egg_name: string | null; offspring: string | null
}
export interface BreederLibrary {
  uid: number; version: number; available: boolean; source: 'observed' | 'history'; pet_count: number
  groups: string[]; natures: string[]; males: BreederParent[]; females: BreederParent[]
  male_total: number; female_total: number; male_page: number; female_page: number; page_size: number
  selected_male: BreederParent | null; selected_female: BreederParent | null
  anchor: number; selection_changed: boolean; prediction: BreederPrediction | null
}
function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === 'object' && !Array.isArray(value) }
function strings(value: unknown): value is string[] { return Array.isArray(value) && value.every(item => typeof item === 'string') }
function numeric(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) }
function nullable(value: unknown): value is number | null { return value === null || numeric(value) }
function parent(value: unknown): value is BreederParent {
  return record(value) && typeof value.gid === 'string' && /^[1-9]\d*$/.test(value.gid)
    && ['name', 'species', 'nature', 'icon_url'].every(key => typeof value[key] === 'string')
    && Number.isSafeInteger(value.dex_no) && (value.gender === 1 || value.gender === 2) && strings(value.groups)
    && nullable(value.voice) && nullable(value.height_ratio) && nullable(value.weight_ratio)
    && typeof value.is_shiny === 'boolean' && typeof value.is_colorful === 'boolean'
    && Array.isArray(value.marks) && value.marks.every(mark => record(mark) && typeof mark.name === 'string'
      && typeof mark.label === 'string' && ['worn', 'reference'].includes(String(mark.source)))
    && (value.location === null || record(value.location) && ['box_id', 'slot', 'row', 'column'].every(key => record(value.location) && Number.isSafeInteger(value.location[key])))
}
function prediction(value: unknown): value is BreederPrediction {
  return record(value) && strings(value.groups) && record(value.natures) && Object.values(value.natures).every(numeric)
    && numeric(value.random_percent) && numeric(value.unknown_percent) && nullable(value.voice)
    && nullable(value.height_ratio) && nullable(value.weight_ratio)
    && (value.egg_name === null || typeof value.egg_name === 'string') && (value.offspring === null || typeof value.offspring === 'string')
}
function valid(value: unknown): value is BreederLibrary {
  return record(value) && ['uid', 'version', 'pet_count', 'male_total', 'female_total', 'male_page', 'female_page', 'page_size'].every(key => Number.isSafeInteger(value[key]) && Number(value[key]) >= 0)
    && Number(value.page_size) > 0 && Number(value.male_page) > 0 && Number(value.female_page) > 0
    && typeof value.available === 'boolean' && ['observed', 'history'].includes(String(value.source))
    && strings(value.groups) && strings(value.natures) && Array.isArray(value.males) && value.males.every(parent)
    && Array.isArray(value.females) && value.females.every(parent)
    && (value.selected_male === null || parent(value.selected_male)) && (value.selected_female === null || parent(value.selected_female))
    && (value.anchor === 0 || value.anchor === 1 || value.anchor === 2) && typeof value.selection_changed === 'boolean'
    && (value.prediction === null || prediction(value.prediction))
}
export function parseBreederLibrary(value: unknown): BreederLibrary {
  if (!valid(value) || value.males.some(row => row.gender !== 1) || value.females.some(row => row.gender !== 2)
    || value.selected_male && value.selected_male.gender !== 1 || value.selected_female && value.selected_female.gender !== 2) {
    throw new Error('筛选配对数据格式错误')
  }
  return value
}

export { parent as isBreederParent }
