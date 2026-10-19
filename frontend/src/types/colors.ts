export interface ColorAxis {
  name: string; hex: string; letter: string
}
export interface ColorCardInfo {
  card_id: string; base_color: string; mix_color: string; name: string
  particle_id: number; particle_name: string
}
export interface ColorPet {
  // 后端给的是实例号整数，串号只在测试夹具里出现，两者都当合法 id。
  gid: number | string; name: string; level: number; gender: number; icon_url: string; card_id: string
  base_name?: string; mix_name?: string
  color_card: ColorCardInfo | null
  // 后端只在 unknown 分组里给：true = 卡号没解析出来（card_id 为空串）
  unresolved?: boolean
}
export interface ColorCell {
  card_id: string; card_number: string; base_name: string; mix_name: string
  base_color: string; mix_color: string; base_letter: string; mix_letter: string
  label: string; names: string; pet_count?: number
}
export interface Colors {
  base_axis: ColorAxis[]; mix_axis: ColorAxis[]
  matrix: Record<string, ColorPet[]>
  // 目录内卡号的格子元数据：有键无 matrix 键即「有卡但没抽到」，与 matrix 同键。
  cells: Record<string, ColorCell>
  catalogs: ColorCell[]
  seasonal: ColorPet[]; unknown: ColorPet[]
  card_total: number; pet_total: number; uid: number; version: number
}
export function matrixKey(baseName: string, mixName: string) { return `${baseName}|${mixName}` }

// 只校验页面消费的字段；新增后端字段不使旧客户端失效。
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}
function isAxis(value: unknown): value is ColorAxis {
  return record(value) && typeof value.name === 'string' && typeof value.hex === 'string'
    && typeof value.letter === 'string'
}
function isFilled(value: unknown) { return typeof value === 'string' && value.length > 0 }
function isId(value: unknown) { return isFilled(value) || (typeof value === 'number' && Number.isSafeInteger(value)) }
function isColorCard(value: unknown): value is ColorCardInfo {
  if (!record(value)) return false
  return ['card_id', 'base_color', 'mix_color', 'name', 'particle_name'].every(key => typeof value[key] === 'string')
    && typeof value.particle_id === 'number' && Number.isSafeInteger(value.particle_id)
}
function isPet(value: unknown): value is ColorPet {
  if (!record(value)) return false
  // unresolved=true 的持有者 card_id 是空串（后端没解析出编号），只有 gid 必须有效。
  if (!isId(value.gid) || typeof value.card_id !== 'string' || typeof value.name !== 'string'
    || typeof value.icon_url !== 'string') return false
  if (value.unresolved !== undefined && typeof value.unresolved !== 'boolean') return false
  if (!Number.isSafeInteger(value.level) || !Number.isSafeInteger(value.gender)) return false
  if (value.base_name !== undefined && typeof value.base_name !== 'string') return false
  if (value.mix_name !== undefined && typeof value.mix_name !== 'string') return false
  // 未收录卡号没有色卡图元，后端回 null；有卡时字段必须完整。
  return value.color_card === null || value.color_card === undefined || isColorCard(value.color_card)
}
function isCell(value: unknown): value is ColorCell {
  if (!record(value)) return false
  if (!isFilled(value.card_id) || !isFilled(value.label) || !isFilled(value.names)) return false
  return ['card_number', 'base_name', 'mix_name', 'base_color', 'mix_color', 'base_letter', 'mix_letter']
    .every(key => typeof value[key] === 'string')
}
// 目录卡片允许暂无色值：只要求卡号与配色名齐备，色块按空字符串跳过。
function isCatalog(value: unknown): value is ColorCell {
  if (!record(value)) return false
  return isFilled(value.card_id) && typeof value.base_name === 'string' && typeof value.mix_name === 'string'
    && ['base_color', 'mix_color', 'base_letter', 'mix_letter', 'label', 'names'].every(key => typeof value[key] === 'string')
}
function ownerPets(value: unknown): value is ColorPet[] {
  return Array.isArray(value) && value.every(isPet)
}
function isMatrix(value: unknown): value is Record<string, ColorPet[]> {
  return record(value) && Object.values(value).every(ownerPets)
}
function metaMap(value: unknown, check: (item: unknown) => item is ColorCell): value is Record<string, ColorCell> {
  return record(value) && Object.values(value).every(check)
}
export function parseColors(value: unknown): Colors {
  if (!record(value) || !Array.isArray(value.base_axis) || !value.base_axis.every(isAxis)
    || !Array.isArray(value.mix_axis) || !value.mix_axis.every(isAxis)
    || !isMatrix(value.matrix) || !metaMap(value.cells, isCell)
    || !list(value.catalogs).every(isCatalog)
    || !ownerPets(value.seasonal) || !ownerPets(value.unknown)
    || !Number.isSafeInteger(value.card_total) || !Number.isSafeInteger(value.pet_total)) {
    throw new Error('色卡数据格式不正确')
  }
  return { base_axis: value.base_axis, mix_axis: value.mix_axis, matrix: value.matrix, cells: value.cells,
    catalogs: list(value.catalogs) as ColorCell[], seasonal: value.seasonal, unknown: value.unknown,
    card_total: Number(value.card_total), pet_total: Number(value.pet_total),
    uid: Number.isSafeInteger(value.uid) ? Number(value.uid) : 0,
    version: Number.isSafeInteger(value.version) ? Number(value.version) : 0 }
}
