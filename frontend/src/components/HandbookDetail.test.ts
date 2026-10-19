import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import HandbookDetail from './HandbookDetail.vue'
import type { HandbookSpecies } from '../types/handbook'

const species = (patch: Partial<HandbookSpecies> = {}): HandbookSpecies => ({
  key: '3001', name: '喵喵', display_name: '喵喵', dex_no: 1, handbook_no: '002', icon_url: '',
  egg_groups: ['动物组'], gender_ratio: [50, 50], height_range: [0.53, 0.75], weight_range: [3.62, 4.6],
  reference_ranges: { height: '0.53-0.75 m', weight: '3.62-4.60 kg' }, has_shiny: false, type_names: ['草'], type_colors: ['#83d256'],
  stats: { hp: 65, atk: 66, spa: 66, def: 49, spd: 91, spe: 33 }, stat_sum: 370, quality: 2, stage: 1,
  max_energy: 10, evolutions: [], chain_members: [], collected: false, owned_count: 0, best_level: 0,
  description: '',
  ...patch,
})

describe('图鉴详情', () => {
  // 详情里的「拥有 N 只」要能回背包预筛，否则用户看到数量却无法查看个体。
  it('已收集时「拥有 N 只」带 data-goto-pets 指向物种名', () => {
    const wrapper = mount(HandbookDetail, { props: { item: species({ collected: true, owned_count: 2, best_level: 60 }) } })
    const button = wrapper.get('[data-goto-pets]')
    expect(button.attributes('data-goto-pets')).toBe('喵喵')
    expect(button.text()).toContain('拥有 2 只 · 最高 Lv60')
  })
  it('未收集时不出现跳转入口', () => {
    const wrapper = mount(HandbookDetail, { props: { item: species() } })
    expect(wrapper.find('[data-goto-pets]').exists()).toBe(false)
    expect(wrapper.text()).toContain('尚未收集')
  })
})
