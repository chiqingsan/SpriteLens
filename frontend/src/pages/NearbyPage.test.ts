import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import NearbyPage from './NearbyPage.vue'
import type { NearbyActor, NearbyMark, NearbySnapshot } from '../types/nearby'
import { flushPromises } from '@vue/test-utils'

function actor(id: string, updated_at: number, marks: NearbyMark[] = [], attention: NearbyActor['attention'] = 'normal'): NearbyActor {
  return {
    actor_id: id, config_id: Number(id), base_id: null, name: `精灵${id}`, icon_url: '', type_names: [], level: 1,
    height: 0, weight: 0, voice: 0, updated_at, marks, attention, position: [Number(id), 0, 0],
  }
}

function snapshot(version: number, actors: NearbyActor[]): NearbySnapshot & { source: 'observed_partial' } {
  return {
    source: 'observed_partial' as const, uid: '1', version, observation_id: 1, phase: 'observing', complete: false, mapping_available: true, radar_radius_raw: 10000,
    scene_id: 1, updated_at: version, unresolved_updates: 0, rejected_actors: 0,
    player_position: [0, 0, 0], position_source: 'client_target', actors,
  }
}

describe('附近精灵更新布局稳定性', () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('nearby-list-pane') ? 680 : 220
    })
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(640)
  })
  afterEach(() => vi.restoreAllMocks())
  it('后台慢请求和实体增删不切换刷新按钮或重置滚动位置', async () => {
    let resolve: (value: unknown) => void = () => {}
    const load = vi.fn().mockResolvedValueOnce(snapshot(1, [actor('1', 1), actor('2', 2)]))
      .mockImplementationOnce(() => new Promise(r => { resolve = r }))
    const wrapper = mount(NearbyPage, { props: { host: { load } } })
    const page = wrapper.vm as unknown as { update(value: unknown): void }
    page.update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    const button = wrapper.get('.nearby-toolbar button')
    const element = button.element
    const viewport = wrapper.get('.nearby-list-pane').element
    viewport.scrollTop = 120
    page.update({ uid: '1', version: 2, observation_id: 1, phase: 'observing' })
    await nextTick()
    expect(button.text()).toBe('刷新')
    expect(button.attributes('disabled')).toBeUndefined()
    expect(button.attributes('aria-busy')).toBe('false')
    resolve(snapshot(2, [actor('2', 3), actor('3', 4)]))
    await flushPromises()
    expect(wrapper.get('.nearby-toolbar button').element).toBe(element)
    expect(button.text()).toBe('刷新')
    expect(viewport.scrollTop).toBe(120)
    wrapper.unmount()
  })

  it('最近观察排序在实时更新时间变化时不重新排列已有精灵', async () => {
    const first = snapshot(1, [actor('1', 1), actor('2', 2), actor('3', 3)])
    const second = snapshot(2, [
      actor('1', 101, [{ label: '粗', name: '粗嗓门', source: 'reference' }], 'marked'),
      actor('2', 100), actor('3', 99),
    ])
    const load = vi.fn().mockResolvedValueOnce(first).mockResolvedValueOnce(second)
    const wrapper = mount(NearbyPage, { props: { host: { load, openFloating: vi.fn() } } })
    ;(wrapper.vm as unknown as { update(value: unknown): void }).update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    await nextTick()
    expect(wrapper.findAll('.nearby-card').map(card => card.attributes('id'))).toEqual([
      'nearby-actor-3', 'nearby-actor-2', 'nearby-actor-1',
    ])

    ;(wrapper.vm as unknown as { update(value: unknown): void }).update({ uid: '1', version: 2, observation_id: 1, phase: 'observing' })
    await flushPromises()
    await nextTick()
    expect(wrapper.findAll('.nearby-card').map(card => card.attributes('id'))).toEqual([
      'nearby-actor-3', 'nearby-actor-2', 'nearby-actor-1',
    ])
    expect(wrapper.findAll('.nearby-card-marks.is-empty')).toHaveLength(2)
  })

  it('超长列表只渲染可视区及缓冲项目', async () => {
    const actors = Array.from({ length: 1000 }, (_, index) => actor(String(index + 1), index + 1))
    const wrapper = mount(NearbyPage, { props: { host: { load: vi.fn().mockResolvedValue(snapshot(1, actors)), openFloating: vi.fn() } } })
    ;(wrapper.vm as unknown as { update(value: unknown): void }).update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    await nextTick()
    const rendered = wrapper.findAll('.nearby-card').length
    expect(rendered).toBeGreaterThan(0)
    expect(rendered).toBeLessThan(actors.length)
    wrapper.unmount()
  })

  it('刷新失败保留同周期列表，并在原位标记稍早结果', async () => {
    const load = vi.fn().mockResolvedValueOnce(snapshot(1, [actor('1', 1)])).mockRejectedValueOnce(new Error('网络断开'))
    const wrapper = mount(NearbyPage, { props: { host: { load, openFloating: vi.fn() } } })
    const page = wrapper.vm as unknown as { update(value: unknown): void; load(): Promise<void> }
    page.update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    expect(wrapper.findAll('.nearby-card')).toHaveLength(1)
    const viewport = wrapper.get('.nearby-list-pane').element
    viewport.scrollTop = 40
    const note = wrapper.get('.nearby-count-note').element
    await page.load()
    await flushPromises()
    expect(wrapper.findAll('.nearby-card')).toHaveLength(1)
    expect(wrapper.get('.nearby-count-note').element).toBe(note)
    expect(wrapper.get('.nearby-count-note').text()).toContain('刷新失败，显示的是稍早的结果')
    expect(wrapper.find('.nearby-error').exists()).toBe(false)
    expect(viewport.scrollTop).toBe(40)
    wrapper.unmount()
  })

  it('无同周期数据时展示错误空态，不保留失效列表', async () => {
    const load = vi.fn().mockRejectedValue(new Error('网络断开'))
    const wrapper = mount(NearbyPage, { props: { host: { load, openFloating: vi.fn() } } })
    ;(wrapper.vm as unknown as { update(value: unknown): void }).update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    expect(wrapper.get('.nearby-error').text()).toContain('网络断开')
    expect(wrapper.find('.nearby-empty').exists()).toBe(true)
    expect(wrapper.findAll('.nearby-card')).toHaveLength(0)
    expect(wrapper.get('.nearby-count-note').text()).toBe('')
    wrapper.unmount()
  })
  it('有牌优先按双牌满、双牌、单牌满、单牌排序，同级保持最近观察', async () => {
    const mark = (name: string): NearbyMark => ({ label: name, name, source: 'reference' })
    const actors = [
      actor('1', 5),                                          // 普通
      actor('2', 4, [mark('满重'), mark('满分')], 'double'),   // 双牌满
      actor('3', 3, [mark('大块头')], 'double'),              // 双牌
      actor('4', 2, [mark('满分')], 'marked'),                // 单牌满
      actor('5', 1, [mark('粗嗓门')], 'marked'),              // 单牌
    ]
    const load = vi.fn().mockResolvedValueOnce(snapshot(1, actors))
    const wrapper = mount(NearbyPage, { props: { host: { load, openFloating: vi.fn() } } })
    ;(wrapper.vm as unknown as { update(value: unknown): void }).update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    await nextTick()
    await wrapper.get('.nearby-sort select').setValue('marks')
    await nextTick()
    expect(wrapper.findAll('.nearby-card').map(card => card.attributes('id'))).toEqual([
      'nearby-actor-2', 'nearby-actor-3', 'nearby-actor-4', 'nearby-actor-5', 'nearby-actor-1',
    ])
    wrapper.unmount()
  })

  it('属性用图标呈现并保留名称作为替代文本', async () => {
    const icons = { '火': '/static/type-icons/type-1.webp', '水': '/static/type-icons/type-2.webp' }
    const target = { ...actor('7', 1), type_names: ['火', '水'] }
    const load = vi.fn().mockResolvedValueOnce({ ...snapshot(1, [target]), type_icons: icons })
    const wrapper = mount(NearbyPage, { props: { host: { load, openFloating: vi.fn() } } })
    ;(wrapper.vm as unknown as { update(value: unknown): void }).update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    await nextTick()
    const rendered = wrapper.findAll('.nearby-type-icon')
    expect(rendered.map(icon => icon.attributes('src'))).toEqual([icons['火'], icons['水']])
    expect(rendered.map(icon => icon.attributes('alt'))).toEqual(['火', '水'])
    wrapper.unmount()
  })

})
