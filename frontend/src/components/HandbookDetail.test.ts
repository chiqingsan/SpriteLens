import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import HandbookDetail from './HandbookDetail.vue'
import type { HandbookSpecies } from '../types/handbook'

const species = (patch: Partial<HandbookSpecies> = {}): HandbookSpecies => ({
  key: '3001', name: '喵喵', display_name: '喵喵', dex_no: 1, handbook_no: '002', icon_url: '',
  types: [6], egg_groups: ['动物组'], gender_ratio: [50, 50], height_range: [53, 75], weight_range: [3620, 4600],
  reference_ranges: { height: '0.53-0.75 m', weight: '3.62-4.60 kg' }, has_shiny: false,
  type_names: ['草'], type_colors: ['#83d256'], matchups: { weak: ['火'], resist: ['水'], immune: [] },
  stats: { hp: 65, atk: 66, spa: 66, def: 49, spd: 91, spe: 33 }, stat_sum: 370, quality: 2, stage: 1,
  max_energy: 10, evolutions: [], chain_members: [], egg: null, description: '',
  ...patch,
})

describe('图鉴详情', () => {
  // 图鉴是 WIKI 资料页：没有账号数据也要完整可用，不能出现背包统计。
  it('不展示任何收集/背包状态', () => {
    const wrapper = mount(HandbookDetail, { props: { item: species() } })
    expect(wrapper.text()).toContain('资料页（不读取账号数据）')
    expect(wrapper.text()).not.toContain('拥有')
    expect(wrapper.text()).not.toContain('已收集')
    expect(wrapper.text()).not.toContain('尚未收集')
    expect(wrapper.find('[data-goto-pets]').exists()).toBe(false)
  })
  it('渲染属性相性的弱点/抵抗/免疫', () => {
    const wrapper = mount(HandbookDetail, { props: { item: species() } })
    const text = wrapper.text()
    expect(text).toContain('属性相性')
    expect(text).toContain('弱点')
    expect(text).toContain('火')
    expect(text).toContain('抵抗')
    expect(text).toContain('水')
  })
  it('有蛋资料时给出孵化时长与蛋图鉴入口', () => {
    const wrapper = mount(HandbookDetail, {
      props: {
        item: species({
          egg: {
            egg_conf_id: 1, name: '喵喵蛋', species_name: '喵喵', hatch_hours: 12,
            hatch_label: '12小时', egg_groups: ['动物组'], egg_type: '普通',
          },
        }),
      },
    })
    expect(wrapper.text()).toContain('喵喵蛋')
    expect(wrapper.text()).toContain('12小时')
    expect(wrapper.get('[data-goto-page]').attributes('data-goto-page')).toBe('egg-dex')
  })
  it('无蛋资料时不出现蛋图鉴入口', () => {
    const wrapper = mount(HandbookDetail, { props: { item: species() } })
    expect(wrapper.find('[data-goto-page]').exists()).toBe(false)
  })
})
