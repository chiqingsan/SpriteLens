import { isWikiReference, type WikiReference } from './wikiReference'

export interface Egg {
  wiki?: WikiReference | null
  can_same_ride?: boolean | null
  egg_conf_id: number; egg_name: string; name: string; base_id: number
  icon_url: string; egg_icon_url: string; handbook_no: string
  egg_type_name: string; hatch_label: string; hatch_seconds: number
  egg_group_names: string[]; gender_male: number; gender_female: number
  reference_ranges: { height: string; weight: string }
  chain: number[]; chain_names: Record<string, string>
}
export interface EggDex {
  eggs: Egg[]; total: number; shown: number; groups: string[]; egg_types: string[]
}

// 只校验页面消费的字段；新增后端字段不使旧客户端失效。
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(item => typeof item === 'string')
}
function isEgg(value: unknown): value is Egg {
  if (!record(value)) return false
  return ['egg_conf_id', 'base_id', 'hatch_seconds', 'gender_male', 'gender_female'].every(
    key => typeof value[key] === 'number' && Number.isFinite(value[key]))
    && ['egg_name', 'name', 'icon_url', 'egg_icon_url', 'handbook_no', 'egg_type_name', 'hatch_label'].every(
      key => typeof value[key] === 'string')
    && isWikiReference(value.wiki)
    && (value.can_same_ride === undefined || value.can_same_ride === null || typeof value.can_same_ride === 'boolean')
    && Number.isSafeInteger(value.egg_conf_id) && Number.isSafeInteger(value.base_id)
    && strings(value.egg_group_names)
    && record(value.reference_ranges) && typeof value.reference_ranges.height === 'string'
    && typeof value.reference_ranges.weight === 'string'
    && Array.isArray(value.chain) && value.chain.every(Number.isSafeInteger)
    && record(value.chain_names) && Object.values(value.chain_names).every(item => typeof item === 'string')
}
export function parseEggDex(value: unknown): EggDex {
  if (!record(value) || !Array.isArray(value.eggs) || !value.eggs.every(isEgg)
    || !Number.isSafeInteger(value.total) || !Number.isSafeInteger(value.shown)
    || !strings(value.groups) || !strings(value.egg_types)) {
    throw new Error('蛋图鉴数据格式不正确')
  }
  return { eggs: value.eggs, total: Number(value.total), shown: Number(value.shown),
    groups: value.groups, egg_types: value.egg_types }
}
