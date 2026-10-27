import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import HandbookDetail from './HandbookDetail.vue'
import type { HandbookSpecies } from '../types/handbook'

const species = (patch: Partial<HandbookSpecies> = {}): HandbookSpecies => ({
  key: '3001', name: '喵喵', display_name: '喵喵', dex_no: 1, handbook_no: '002', artwork_url: '', shiny_artwork_url: '', icon_url: '',
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
    expect(wrapper.text()).not.toContain('拥有')
    expect(wrapper.text()).not.toContain('已收集')
    expect(wrapper.text()).not.toContain('尚未收集')
    expect(wrapper.find('[data-goto-pets]').exists()).toBe(false)
  })
  it('渲染有数据的属性相性并隐藏空分组', () => {
    const wrapper = mount(HandbookDetail, { props: { item: species() } })
    const text = wrapper.text()
    expect(text).toContain('属性相性')
    expect(text).toContain('弱点')
    expect(text).toContain('火')
    expect(text).toContain('抵抗')
    expect(text).toContain('水')
    expect(text).not.toContain('免疫')
    expect(wrapper.find('.dex-matchup-group.is-immune').exists()).toBe(false)
  })
  it('没有有效属性相性时隐藏整个区块', () => {
    const wrapper = mount(HandbookDetail, { props: { item: species({ matchups: { weak: [], resist: [], immune: [] } }) } })
    expect(wrapper.find('.dex-matchups').exists()).toBe(false)
  })
  it('数据范围显示数值端点和范围跨度，并隐藏空分布', () => {
    const wrapper = mount(HandbookDetail, { props: { item: species() } })
    const text = wrapper.text()
    expect(text).toContain('身高 0.53–0.75 m')
    expect(text).toContain('0.53 m')
    expect(text).toContain('0.75 m')
    expect(text).toContain('范围跨度 0.22 m')
    expect(text).toContain('小不点 ≤0.53m · 大块头 ≥0.75m')
    expect(text).toContain('体重 3.62–4.60 kg')
    expect(text).toContain('范围跨度 0.98 kg')
    expect(text).toContain('体型参考')
    expect(text).toContain('小不点 ≤3.64kg · 大块头 ≥4.58kg')
    expect(text).toContain('粗嗓门 −100–−96 dB')
    expect(text).toContain('婉转声 96–100 dB')
    expect(text).not.toContain('栖息分布')
    expect(text).not.toContain('暂无分布数据')
  })
  it('不展示技能、描述和活动特殊蛋来源', () => {
    const wrapper = mount(HandbookDetail, { props: { item: species({ description: '不应展示的描述' }) } })
    const text = wrapper.text()
    expect(text).not.toContain('技能资料')
    expect(text).not.toContain('不应展示的描述')
    expect(text).not.toContain('活动与特殊蛋来源')
    expect(text).not.toContain('特殊蛋说明与来源')
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
    expect(wrapper.get('[data-goto-page]').attributes('title')).toContain('喵喵蛋 · 12小时')
    expect(wrapper.get('[data-goto-page]').attributes('data-goto-page')).toBe('egg-dex')
  })
  it('无蛋资料时不出现蛋图鉴入口', () => {
    const wrapper = mount(HandbookDetail, { props: { item: species() } })
    expect(wrapper.find('[data-goto-page]').exists()).toBe(false)
  })
  it('进化链提供横向拖动容器', () => {
    const wrapper = mount(HandbookDetail, {
      props: {
        item: species({
          chain_members: [
            { key: '3001', name: '喵喵', stage: 1 },
            { key: '3002', name: '喵呜', stage: 2 },
            { key: '3003', name: '魔力猫', stage: 3 },
            { key: '3004', name: '超长名称精灵形态', stage: 4 },
          ],
        }),
      },
    })
    const family = wrapper.get('.mini-family-members')
    expect(family.attributes('tabindex')).toBe('0')
    expect(family.attributes('aria-label')).toContain('可按住鼠标拖动')
  })
})
