import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ColorsPage from './ColorsPage.vue'

const pet = (gid: string, cardId: string) => ({
  gid, name: `宠物${gid}`, level: 30, gender: 2,
  icon_url: `/static/pet-media/${gid}.webp`, card_id: cardId,
  color_card: { card_id: cardId, base_color: '#112233', mix_color: '#445566', name: '红底 · 蓝混', particle_id: 1, particle_name: '四角星' },
})

const cell = (cardId: string, label: string, names: string) => ({
  card_id: cardId, card_number: cardId,
  base_name: '红', mix_name: '蓝', base_color: '#112233', mix_color: '#445566',
  base_letter: 'A', mix_letter: 'A', label, names,
})

const payload = {
  base_axis: [
    { name: '红', hex: '#112233', letter: 'A' },
    { name: '绿', hex: '#778899', letter: 'B' },
    { name: '黄', hex: '#aabbcc', letter: 'C' },
  ],
  mix_axis: [{ name: '蓝', hex: '#445566', letter: 'A' }],
  matrix: { '红|蓝': [pet('1001', '101')] },
  cells: {
    '红|蓝': { ...cell('101', 'A1', '红底 · 蓝混'), pet_count: 1 },
    '绿|蓝': cell('102', 'B1', '绿底 · 蓝混'),
  },
  catalogs: [cell('101', 'A1', '红底 · 蓝混'), cell('102', 'B1', '绿底 · 蓝混')],
  seasonal: [pet('1002', 's1')],
  unknown: [{ ...pet('1003', ''), color_card: null }],
  card_total: 3, pet_total: 2, uid: 101, version: 7,
}

const fullBaseAxis = Array.from({ length: 11 }, (_, index) => ({
  name: index === 0 ? '红' : index === 1 ? '绿' : `底色${index + 1}`,
  hex: `#${String(index + 1).padStart(2, '0')}2233`,
  letter: String.fromCharCode(65 + index),
}))
const fullMixAxis = ['蓝', '青', '紫', '黄'].map((name, index) => ({
  name, hex: `#44${String(index + 5).padStart(2, '0')}66`, letter: String.fromCharCode(65 + index),
}))
const fullCatalogs = Array.from({ length: 44 }, (_, index) => {
  const seasonal = index === 43
  const base = seasonal ? { name: '赛季', hex: '#e9cf94' } : fullBaseAxis[index % fullBaseAxis.length]!
  const mix = seasonal ? { name: 'S1', hex: '#e0c8ff' } : fullMixAxis[Math.floor(index / fullBaseAxis.length)]!
  return {
    ...cell(index === 0 ? '101' : index === 1 ? '102' : seasonal ? 's1' : String(200 + index), `C${index + 1}`, `色卡 ${index + 1}`),
    base_name: base.name, base_color: base.hex, mix_name: mix.name, mix_color: mix.hex,
  }
})
const fullCatalogPayload = {
  ...payload,
  base_axis: fullBaseAxis,
  mix_axis: fullMixAxis,
  catalogs: fullCatalogs,
  card_total: 44,
}

function page(api: (path: string, signal?: AbortSignal) => Promise<unknown>) {
  return mount(ColorsPage, { props: { api, active: true } })
}

describe('色卡页面蛋神式矩阵布局', () => {
  it('个人色卡只显示当前账号拥有的卡，图鉴保留目录状态语义', async () => {
    const wrapper = page(vi.fn().mockResolvedValue(payload))
    await flushPromises()
    const cells = wrapper.findAll('#cl-matrix .matrix-card-cell')
    expect(cells).toHaveLength(3)
    expect(cells.map(node => node.attributes('data-state'))).toEqual(['pets', 'empty', 'empty'])
    expect(cells[0]!.find('.color-card').exists()).toBe(true)
    expect(cells[0]!.find('.color-cell-owners').exists()).toBe(false)
    expect(cells[1]!.find('.color-card').exists()).toBe(false)
    expect(cells[1]!.text()).toBe('—')
    expect(cells[2]!.text()).toBe('—')
    expect(wrapper.find('#color-count').text()).toBe('已收录 2 / 3 张')
    expect(wrapper.find('#color-pet-count').text()).toBe('2 只精灵')
    expect(wrapper.find('#color-filter-button').exists()).toBe(false)

  })

  it('点击或 Enter 在右侧展示持有者与独立花纹，空数据仍保留矩阵骨架', async () => {
    const wrapper = page(vi.fn().mockResolvedValue(payload))
    await flushPromises()
    expect(wrapper.find('.colors-selection').text()).toContain('选择色卡格查看持有状态')
    const cells = wrapper.findAll('#cl-matrix .matrix-card-cell')
    await cells[0]!.trigger('click')
    expect(cells[0]!.classes()).toContain('selected')
    expect(wrapper.find('.selection-owners').text()).toContain('宠物1001')
    expect(wrapper.find('.inspector-pet').attributes('data-mm')).toBe('1001')
    expect(wrapper.find('.inspector-pet-face img').attributes('src')).toContain('pattern_sparkle_four.webp')
    expect(cells[0]!.find('.color-cell-owners').exists()).toBe(false)
    expect(wrapper.find('.colors-selection').text()).toContain('红底 · 蓝混')
    await wrapper.find('.color-main-tabs button:nth-child(2)').trigger('click')
    expect(wrapper.find('.colors-selection').text()).toContain('选择色卡格查看持有状态')

    const emptyWrapper = page(vi.fn().mockResolvedValue({
      ...payload, matrix: {}, cells: { '红|蓝': { ...cell('101', 'A1', '红底 · 蓝混'), pet_count: 0 } },
      pet_total: 0, seasonal: [], unknown: [],
    }))
    await flushPromises()
    expect(emptyWrapper.find('#cl-matrix .matrix-card-cell[data-state="card"] .color-card').exists()).toBe(false)
    expect(emptyWrapper.find('#cl-empty').isVisible()).toBe(true)
  })

  it('默认是个人色卡，图鉴矩阵展示 44 张并支持状态、底色、混色筛选', async () => {
    const wrapper = page(vi.fn().mockResolvedValue(fullCatalogPayload))
    await flushPromises()
    expect(wrapper.find('.color-main-tabs button[aria-selected="true"]').text()).toBe('我的色卡')
    expect(wrapper.find('#color-count').text()).toBe('已收录 2 / 44 张')
    expect(wrapper.find('#cl-matrix .matrix-card-cell[data-card-id="s1"]').attributes('data-state')).toBe('pets')

    await wrapper.find('.color-main-tabs button:nth-child(2)').trigger('click')
    expect(wrapper.find('.color-main-tabs button[aria-selected="true"]').text()).toBe('完整图鉴')
    expect(wrapper.find('#color-count').text()).toBe('图鉴 44 / 44 张')
    expect(wrapper.findAll('#cl-matrix .matrix-card-cell[data-card-id]')).toHaveLength(44)
    expect(wrapper.find('#cl-matrix .matrix-card-cell[data-card-id="101"]').attributes('data-state')).toBe('pets')
    expect(wrapper.find('#cl-matrix .matrix-card-cell[data-card-id="102"]').attributes('data-state')).toBe('card')

    await wrapper.find('#color-filter-button').trigger('click')
    expect(wrapper.find('.catalog-status-filter.active').attributes('data-value')).toBe('all')
    await wrapper.find('.catalog-status-filter[data-value="owned"]').trigger('click')
    expect(wrapper.find('#color-count').text()).toBe('图鉴 2 / 44 张')
    expect(wrapper.findAll('#cl-matrix .matrix-card-cell[data-card-id]')).toHaveLength(2)
    await wrapper.find('.catalog-status-filter[data-value="unowned"]').trigger('click')
    expect(wrapper.find('#color-count').text()).toBe('图鉴 42 / 44 张')
    await wrapper.find('.catalog-status-filter[data-value="seasonal"]').trigger('click')
    expect(wrapper.findAll('#cl-matrix .matrix-card-cell[data-card-id]')).toHaveLength(1)
    await wrapper.find('.catalog-status-filter[data-value="all"]').trigger('click')
    await wrapper.find('.catalog-base-filter[data-value="绿"]').trigger('click')
    expect(wrapper.find('#color-count').text()).toBe('图鉴 4 / 44 张')
    await wrapper.find('.catalog-base-filter[data-value=""]').trigger('click')
    await wrapper.find('.catalog-mix-filter[data-value="青"]').trigger('click')
    expect(wrapper.find('#color-count').text()).toBe('图鉴 11 / 44 张')
    await wrapper.find('.catalog-status-filter[data-value="owned"]').trigger('click')
    await wrapper.find('.catalog-base-filter[data-value="绿"]').trigger('click')
    await wrapper.find('.catalog-mix-filter[data-value="青"]').trigger('click')
    expect(wrapper.find('#color-count').text()).toBe('图鉴 0 / 44 张')
    expect(wrapper.find('.inline-state').text()).toContain('当前筛选没有匹配的色卡')
  })

  it('切换 Tab 保留图鉴筛选，切号重置清除筛选和选中但保留当前 Tab', async () => {
    const wrapper = page(vi.fn().mockResolvedValue(fullCatalogPayload))
    await flushPromises()
    await wrapper.find('.color-main-tabs button:nth-child(2)').trigger('click')
    await wrapper.find('#color-filter-button').trigger('click')
    await wrapper.find('.catalog-status-filter[data-value="seasonal"]').trigger('click')
    await wrapper.find('#cl-matrix .matrix-card-cell[data-card-id]').trigger('click')
    expect(wrapper.find('.colors-selection').text()).not.toContain('选择色卡格查看持有状态')
    await wrapper.find('.color-main-tabs button:nth-child(1)').trigger('click')
    await wrapper.find('.color-main-tabs button:nth-child(2)').trigger('click')
    expect(wrapper.find('.catalog-status-filter.active').attributes('data-value')).toBe('seasonal')
    expect(wrapper.find('.colors-selection').text()).toContain('选择色卡格查看持有状态')

    const reset = (wrapper.vm as unknown as { resetAccount: () => void }).resetAccount
    reset()
    await flushPromises()
    expect(wrapper.find('.color-main-tabs button[aria-selected="true"]').text()).toBe('完整图鉴')
    expect(wrapper.find('#color-filter-button').text()).toContain('全部条件')
    expect(wrapper.find('.colors-selection').text()).toContain('选择色卡格查看持有状态')
    expect(wrapper.find('#color-matrix').text()).toContain('暂无色卡数据')
  })

  it('刷新失败保留旧数据并提供重试，加载未完成时不下结论', async () => {
    const api = vi.fn().mockRejectedValueOnce(new Error('服务不可用')).mockResolvedValue(payload)
    const wrapper = page(api)
    await flushPromises()
    expect(wrapper.find('#color-matrix [role="alert"]').text()).toContain('色卡加载失败：服务不可用')
    await wrapper.find('#color-matrix [role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('#color-matrix [role="alert"]').exists()).toBe(false)
    expect(wrapper.findAll('#cl-seasonal .color-owner')).toHaveLength(1)
    expect(wrapper.find('#cl-unknown').text()).toContain('宠物1003')

    let settle!: (value: unknown) => void
    const pending = new Promise(resolve => { settle = resolve })
    const pendingWrapper = page(vi.fn().mockReturnValue(pending))
    expect(pendingWrapper.find('#cl-seasonal-count').text()).toBe('')
    settle(payload)
    await flushPromises()
    expect(pendingWrapper.find('#cl-seasonal-count').text()).toBe('1 只赛季卡')
  })
})
