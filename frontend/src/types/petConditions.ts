import type { PetFilters } from './petFilters'
export const measures = [['voice', '声音', 'dB', '1'],
  ['height_position', '身高', '%', '.1'], ['weight_position', '体重', '%', '.1']] as const
export type RangeKey = `${typeof measures[number][0]}_${'min' | 'max'}`
export interface AdvancedFilters { egg_groups: string[]; egg_mode: 'any' | 'all' }
export type PetRanges = Record<RangeKey, number | null>
export function emptyRanges(): PetRanges {
  return Object.fromEntries(measures.flatMap(([field]) => [`${field}_min`, `${field}_max`].map(key => [key, null]))) as PetRanges
}
export type PetConditions = Omit<PetFilters, 'sort' | 'desc'> & AdvancedFilters & PetRanges
export interface PetShortcut { name: string; filters: Partial<PetConditions> }
export const markMedals: Record<number, string> = { 1001: '大块头', 1002: '小不点', 1026: '婉转声', 1025: '粗嗓门' }
export const defaultPetShortcuts: PetShortcut[] = ['大块头', '小不点', '婉转声', '粗嗓门'].map(name => ({ name, filters: { marks: [name] } }))
const removedKeys = ['talent_min', 'height_min', 'height_max', 'weight_min', 'weight_max']
const keys = ['search', 'level_min', 'level_max', 'natures', 'types', 'medals', ...removedKeys, 'gender', 'egg_groups', 'egg_mode', 'pool', 'pool_mode', 'shiny', 'colorful', 'medal', 'marks', 'speciality', 'acquisition', 'captured_days', ...Object.keys(emptyRanges())]
function conditions(value: unknown): value is Partial<PetConditions> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  return Object.entries(value).every(([key, item]) => {
    if (!keys.includes(key)) return false
    if (key === 'shiny' || key === 'colorful') return typeof item === 'boolean'
    if (key === 'pool_mode') return item === 'and' || item === 'or'
    if (key === 'pool' || key === 'marks') return Array.isArray(item) && item.every(value => typeof value === 'string' && (key === 'pool' ? ['medal', 'male', 'shiny', 'max_height', 'max_weight'] : ['大块头', '小不点', '婉转声', '粗嗓门']).includes(value))
    if (key === 'medal' || key === 'speciality' || key === 'acquisition' || key === 'captured_days') return typeof item === 'number' && Number.isSafeInteger(item) && item >= 0 && (key !== 'captured_days' || [0, 1, 3, 7].includes(item))
    if (['natures', 'medals', 'types', 'egg_groups'].includes(key)) return Array.isArray(item) && item.every(element => key === 'natures' || key === 'medals' ? Number.isSafeInteger(element) && element >= (key === 'medals' ? 1 : 0) : typeof element === 'string')
    if (key === 'search') return typeof item === 'string'
    if (key === 'egg_mode') return item === 'any' || item === 'all'
    if (['level_min', 'level_max', 'talent_min', 'gender'].includes(key)) return typeof item === 'number' && Number.isSafeInteger(item) && item >= 0
    return item === null || typeof item === 'number' && Number.isFinite(item) && (key.startsWith('voice') || item >= 0) && (!key.includes('_position_') || item <= 100)
  })
}
export function parsePetConditions(value: unknown): Partial<PetConditions> {
  if (!conditions(value)) throw new Error('宠物筛选条件格式不正确')
  // 旧快捷和服务端响应中的已移除条件不再进入界面状态，避免隐藏筛选。
  return Object.fromEntries(Object.entries(value).filter(([key]) => !removedKeys.includes(key))
    .map(([key, item]) => [key, key === 'pool' ? (item as string[]).filter(name => !['max_height', 'max_weight'].includes(name)) : item]))
}
export function parsePetShortcuts(value: unknown): PetShortcut[] {
  if (!Array.isArray(value) || value.length > 256) throw new Error('快捷条件格式不正确')
  return value.map(item => {
    if (!item || typeof item !== 'object' || typeof item.name !== 'string' || !item.name.trim() || item.name.length > 40) throw new Error('快捷条件名称无效')
    let filters = parsePetConditions(item.filters)
    if (filters.medal) {
      const preset = markMedals[filters.medal]
      filters = { ...filters, ...(preset ? { marks: [...new Set([...(filters.marks || []), preset])] } : { medals: [...new Set([...(filters.medals || []), filters.medal])] }) }
      delete filters.medal
    }
    return { name: item.name.replace(/^(奖牌|系别|性格|蛋组|特性|获取方式|获取|捕获)\s*[·：:]\s*/, ''), filters }
  }).filter((item, index, items) => items.findIndex(value => JSON.stringify(value.filters) === JSON.stringify(item.filters)) === index)
}
