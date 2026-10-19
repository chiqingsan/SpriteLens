import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ColorsPage from './ColorsPage.vue'

const pet = (gid: string, cardId: string) => ({ gid, name: `宠物${gid}`, level: 30, gender: 2,
  icon_url: `/static/pet-media/${gid}.webp`, card_id: cardId,
  color_card: { card_id: cardId, base_color: '#112233', mix_color: '#445566', name: '红底 · 蓝混', particle_id: 1, particle_name: '四角星' } })
const cell = (cardId: string, label: string, names: string) => ({ card_id: cardId, card_number: cardId,
  base_name: '红', mix_name: '蓝', base_color: '#112233', mix_color: '#445566',
  base_letter: 'A', mix_letter: 'A', label, names })
// 红|蓝 = 有卡有持有者；绿|蓝 = 有卡无持有者；黄|蓝 = 目录里没这张卡。
const payload = {
  base_axis: [{ name: '红', hex: '#112233', letter: 'A' }, { name: '绿', hex: '#778899', letter: 'B' }, { name: '黄', hex: '#aabbcc', letter: 'C' }],
  mix_axis: [{ name: '蓝', hex: '#445566', letter: 'A' }],
  matrix: { '红|蓝': [pet('1001', '101')] },
  cells: { '红|蓝': { ...cell('101', 'A1', '红底 · 蓝混'), pet_count: 1 }, '绿|蓝': cell('102', 'B1', '绿底 · 蓝混') },
  catalogs: [cell('101', 'A1', '红底 · 蓝混'), cell('102', 'B1', '绿底 · 蓝混')],
  seasonal: [pet('1002', 's1')], unknown: [{ ...pet('1003', ''), color_card: null }],
  card_total: 3, pet_total: 2, uid: 101, version: 7,
}
function page(api: (path: string, signal?: AbortSignal) => Promise<unknown>) {
  return mount(ColorsPage, { props: { api, active: true } })
}
describe('色卡页面三态渲染', () => {
  it('有持有者出 mm-pet 芯片与色卡图元，有卡无持有者出卡面，无卡出 —', async () => {
    const wrapper = page(vi.fn().mockResolvedValue(payload))
    await flushPromises()
    const cells = wrapper.findAll('#cl-matrix tbody .mm-cell')
    expect(cells.map(node => node.classes())).toEqual([['mm-cell'], ['mm-cell'], ['mm-cell', 'empty']])
    expect(cells[0]!.findAll('.mm-pet')).toHaveLength(1)
    expect(cells[0]!.find('.mm-pet').text()).toContain('宠物1001')
    expect(cells[0]!.find('.mm-pet').text()).toContain('Lv30')
    // 外壳在 #page-colors 上监听 [data-mm] 点芯片跳精灵页，原生 petChip 也带这个属性。
    expect(cells[0]!.find('.mm-pet').attributes('data-mm')).toBe('1001')
    expect(cells[0]!.findAll('.pet-color-card')).toHaveLength(1)
    expect(cells[1]!.find('.cc-label').text()).toBe('B1')
    expect(cells[1]!.find('.cc-names').text()).toBe('绿底 · 蓝混')
    expect(cells[1]!.findAll('.pet-color-card')).toHaveLength(1)
    expect(cells[2]!.text()).toBe('—')
    expect(wrapper.find('#cl-meta').text()).toBe('收录 2 / 3 张 · 持有者 2 只 · 赛季卡 1 只')
  })
  it('全部无持有者时矩阵不落成空白，空状态提示按 pet_total 控制', async () => {
    const wrapper = page(vi.fn().mockResolvedValue({ ...payload, matrix: {},
      cells: { '红|蓝': { ...cell('101', 'A1', '红底 · 蓝混'), pet_count: 0 } }, pet_total: 0, seasonal: [], unknown: [] }))
    await flushPromises()
    const target = wrapper.findAll('#cl-matrix tbody .mm-cell')[0]!
    expect(target.classes()).toEqual(['mm-cell'])
    expect(target.find('.cc-label').text()).toBe('A1')
    expect(target.find('.cc-names').text()).toBe('红底 · 蓝混')
    expect(target.find('.pet-color-card').exists()).toBe(true)
    // 与原生一致：空状态提示常驻 DOM（v-show），各自按统计口径开关。
    expect((wrapper.find('#cl-empty').element as HTMLElement).style.display).not.toBe('none')
    expect((wrapper.find('#cl-seasonal-empty').element as HTMLElement).style.display).not.toBe('none')
    expect((wrapper.find('#cl-unknown-empty').element as HTMLElement).style.display).not.toBe('none')
  })
  it('加载失败显示错误与重试，赛季卡/未收录分组带编号', async () => {
    const api = vi.fn().mockRejectedValueOnce(new Error('服务不可用')).mockResolvedValue(payload)
    const wrapper = page(api)
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('色卡加载失败：服务不可用')
    await wrapper.find('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect((wrapper.find('#cl-empty').element as HTMLElement).style.display).toBe('none')
    expect(wrapper.findAll('#cl-seasonal .mm-pet')).toHaveLength(1)
    expect(wrapper.find('#cl-unknown').text()).toContain('宠物1003')
  })
  it('数据未到位时不给赛季卡/未收录分组下空状态结论', async () => {
    let settle!: (value: unknown) => void
    const pending = new Promise(resolve => { settle = resolve })
    const wrapper = page(vi.fn().mockReturnValue(pending))
    const display = (selector: string) => (wrapper.find(selector).element as HTMLElement).style.display
    expect(display('#cl-seasonal-empty')).toBe('none')
    expect(display('#cl-unknown-empty')).toBe('none')
    expect(wrapper.find('#cl-seasonal-count').text()).toBe('')
    expect(wrapper.find('#cl-unknown-count').text()).toBe('')
    settle(payload)
    await flushPromises()
    expect(wrapper.find('#cl-seasonal-count').text()).toBe('1 只')
    expect(wrapper.find('#cl-unknown-count').text()).toBe('1 只')
    expect(display('#cl-seasonal-empty')).toBe('none')
  })
})
