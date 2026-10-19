import { effectScope, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useColors } from './useColors'
import { parseColors } from '../types/colors'

// 真实 /api/colors 的 gid 是整数实例号，夹具照此用数字，另留一例容忍字符串。
const pet = (gid: number | string, cardId: string, colorCard: unknown = null) => ({
  gid, name: `宠物${gid}`, level: 30, gender: 1, icon_url: `/static/pet-media/${gid}.webp`,
  card_id: cardId, color_card: colorCard,
})
const face = (cardId: string) => ({ card_id: cardId, base_color: '#112233', mix_color: '#445566',
  name: '红底 · 蓝混', particle_id: 1, particle_name: '四角星' })
const cell = (cardId: string, label: string, names: string) => ({ card_id: cardId, card_number: cardId,
  base_name: '红', mix_name: '蓝', base_color: '#112233', mix_color: '#445566',
  base_letter: 'A', mix_letter: 'A', label, names, pet_count: 0 })
// 红|蓝 = 有卡有持有者；绿|蓝 = 有卡无持有者；黄|蓝 = 目录里没这张卡（无 cells 键）。
const payload = {
  base_axis: [{ name: '红', hex: '#112233', letter: 'A' }, { name: '绿', hex: '#778899', letter: 'B' }, { name: '黄', hex: '#aabbcc', letter: 'C' }],
  mix_axis: [{ name: '蓝', hex: '#445566', letter: 'A' }],
  matrix: { '红|蓝': [pet(1001, '101', face('101'))] },
  cells: { '红|蓝': { ...cell('101', 'A1', '红底 · 蓝混'), pet_count: 1 }, '绿|蓝': cell('102', 'B1', '绿底 · 蓝混') },
  catalogs: [cell('101', 'A1', '红底 · 蓝混'), cell('102', 'B1', '绿底 · 蓝混')],
  seasonal: [pet(1002, 's1', face('s1'))], unknown: [pet(1003, '')],
  card_total: 3, pet_total: 3, uid: 101, version: 7,
}
const scopes: ReturnType<typeof effectScope>[] = []
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()) })
function setup(api: Parameters<typeof useColors>[0]) {
  const scope = effectScope(); scopes.push(scope)
  return scope.run(() => useColors(api))!
}
describe('色卡三态与请求生命周期', () => {
  it('三态按 cells/matrix 有键判定：无卡为 —、有卡无持有者出卡面、有持有者出芯片', async () => {
    const model = setup(vi.fn().mockResolvedValue(payload))
    await model.load()
    const row = model.matrixRows.value[0]
    expect(row.cells.map(item => item.state)).toEqual(['pets', 'card', 'empty'])
    expect(row.cells[1]).toMatchObject({ cell: { label: 'B1', names: '绿底 · 蓝混' } })
    expect(model.metaText.value).toBe('收录 2 / 3 张 · 持有者 3 只 · 赛季卡 1 只')
  })
  it('matrix 有空数组但 cells 有键时仍算「有卡无持有者」，不落成空位', async () => {
    const model = setup(vi.fn().mockResolvedValue({ ...payload, matrix: { '绿|蓝': [] } }))
    await model.load()
    expect(model.matrixRows.value[0].cells.map(item => item.state)).toEqual(['card', 'card', 'empty'])
  })
  it('坏载荷报「色卡数据格式不正确」，服务失败可见且支持重试', async () => {
    const api = vi.fn().mockResolvedValueOnce({ ...payload, cells: { '红|蓝': { card_id: '101' } } })
      .mockRejectedValueOnce(new Error('读取失败')).mockResolvedValue(payload)
    const model = setup(api)
    await model.load(); expect(model.error.value).toBe('色卡数据格式不正确')
    await model.load(); expect(model.error.value).toBe('读取失败')
    await model.load(); expect(model.error.value).toBe('')
    expect(model.data.value?.pet_total).toBe(3)
  })
  it('离页取消在途请求并丢弃晚到响应，重进按已加载状态补拉', async () => {
    const pending: Array<{ resolve: (data: unknown) => void; signal?: AbortSignal }> = []
    const api = vi.fn((_path: string, signal?: AbortSignal) => new Promise<unknown>(resolve => pending.push({ resolve, signal })))
    const model = setup(api)
    const first = model.load()
    // 先取批准对象，断言失败也不至于让下面的 await 挂住测试。
    const request = pending[0]!
    expect(api).toHaveBeenCalledWith('/api/colors', request.signal)
    model.pause()
    expect(request.signal?.aborted).toBe(true)
    const second = model.resume()
    expect(api).toHaveBeenCalledTimes(2)
    request.resolve({ ...payload, pet_total: 99 })
    await first
    // 晚到响应被丢弃：数据仍空，loading 由重进发起的新请求维持。
    expect(model.data.value).toBeNull(); expect(model.loading.value).toBe(true)
    pending[1]!.resolve(payload)
    await second
    expect(model.data.value?.pet_total).toBe(3)
    expect(model.loading.value).toBe(false)
    await model.resume()
    expect(api).toHaveBeenCalledTimes(2)
  })
  it('离页保留已加载数据，切号清空等待重拉', async () => {
    const api = vi.fn().mockResolvedValue(payload), model = setup(api)
    await model.load()
    model.pause()
    await model.resume()
    expect(api).toHaveBeenCalledTimes(1); expect(model.data.value?.uid).toBe(101)
    model.resetAccount()
    expect(model.data.value).toBeNull(); expect(model.error.value).toBe('')
    const again = model.resume()
    expect(api).toHaveBeenCalledTimes(2)
    await again
  })
  it('scope 销毁后晚到响应不写入', async () => {
    let resolve!: (value: unknown) => void
    const api = vi.fn(() => new Promise<unknown>(done => { resolve = done }))
    const scope = effectScope()
    const model = scope.run(() => useColors(api))!
    const loading = model.load()
    scope.stop(); resolve(payload); await loading; await nextTick()
    expect(model.data.value).toBeNull()
  })
})
describe('parseColors 字段校验', () => {
  it('未收录卡号的空色卡图元可用，缺轴/缺统计抛错', () => {
    expect(parseColors({ ...payload, unknown: [pet(1003, '', null)] }).unknown[0].color_card).toBeNull()
    expect(() => parseColors({ ...payload, pet_total: '3' })).toThrow('色卡数据格式不正确')
    expect(() => parseColors({ ...payload, base_axis: [{ name: '红' }] })).toThrow('色卡数据格式不正确')
    expect(() => parseColors(null)).toThrow('色卡数据格式不正确')
  })
  // 回归：真实载荷的 gid 是整数，早期校验只收字符串，导致色卡页整页报「格式不正确」。
  it('gid 接受整数实例号（真实载荷形态），也容忍字符串', () => {
    expect(parseColors(payload).matrix['红|蓝'][0].gid).toBe(1001)
    const stringGid = { ...payload, matrix: { '红|蓝': [pet('1001', '101', face('101'))] } }
    expect(parseColors(stringGid).matrix['红|蓝'][0].gid).toBe('1001')
    expect(() => parseColors({ ...payload, matrix: { '红|蓝': [pet('', '101')] } })).toThrow('色卡数据格式不正确')
  })
})
