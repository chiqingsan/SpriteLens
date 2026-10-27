import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import NearbyPage from './NearbyPage.vue'
import SceneMap from '../components/SceneMap.vue'
import type { NearbyActor, NearbyMark, NearbySnapshot } from '../types/nearby'
import { flushPromises } from '@vue/test-utils'

function actor(id: string, updated_at: number, marks: NearbyMark[] = [], attention: NearbyActor['attention'] = 'normal'): NearbyActor {
  return {
    actor_id: id, config_id: Number(id), base_id: null, name: `精灵${id}`, icon_url: '', type_names: [], level: 1,
    height: 0, weight: 0, voice: 0, updated_at, marks, attention, position: [Number(id), 0, 0],
    chain_names: [],
  }
}

function snapshot(version: number, actors: NearbyActor[]): NearbySnapshot & { source: 'observed_partial' } {
  return {
    source: 'observed_partial' as const, uid: '1', version, observation_id: 1, phase: 'observing', complete: false, mapping_available: true, radar_radius_raw: 10000,
    scene_id: 1, updated_at: version, unresolved_updates: 0, rejected_actors: 0,
    player_position: [0, 0, 0], position_source: 'client_target', actors, type_icons: {},
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
  it('范围待实测时提示搜索覆盖已暂停，附近精灵仍显示', async () => {
    const load = vi.fn().mockResolvedValue({ ...snapshot(1, [actor('1', 1)]), coverage_paused: true })
    const wrapper = mount(NearbyPage, { props: { host: { load } } })
    ;(wrapper.vm as unknown as { update(value: unknown): void }).update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    expect(wrapper.get('.nearby-count-note').text()).toBe('记录已暂停')
    expect(wrapper.get('.nearby-count-note').attributes('title')).toContain('服务器下发范围尚待实测')
    expect(wrapper.find('.nearby-card').exists()).toBe(true)
    wrapper.unmount()
  })
  it('版本不变时后台写入失败与恢复也更新状态提示', async () => {
    const load = vi.fn().mockResolvedValue({ ...snapshot(1, [actor('1', 1)]), coverage_paused: true })
    const wrapper = mount(NearbyPage, { props: { host: { load } } })
    const page = wrapper.vm as unknown as { update(value: unknown): void }
    page.update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    page.update({ uid: '1', version: 1, observation_id: 1, phase: 'observing', coverage_error: '磁盘不可写' })
    await nextTick()
    expect(wrapper.get('.nearby-count-note').text()).toBe('搜索记录异常')
    expect(wrapper.get('.nearby-count-note').attributes('title')).toContain('磁盘不可写')
    page.update({ uid: '1', version: 1, observation_id: 1, phase: 'observing', coverage_error: null })
    await nextTick()
    expect(wrapper.get('.nearby-count-note').text()).toBe('记录已暂停')
    wrapper.unmount()
  })
  it('后台慢请求和实体增删不切换刷新按钮或重置滚动位置', async () => {
    let resolve: (value: unknown) => void = () => {}
    const load = vi.fn().mockResolvedValueOnce(snapshot(1, [actor('1', 1), actor('2', 2)]))
      .mockImplementationOnce(() => new Promise(r => { resolve = r }))
    const wrapper = mount(NearbyPage, { props: { host: { load } } })
    const page = wrapper.vm as unknown as { update(value: unknown): void }
    page.update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    const button = wrapper.get('.nearby-toolbar .nearby-refresh')
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
    expect(wrapper.get('.nearby-toolbar .nearby-refresh').element).toBe(element)
    expect(button.text()).toBe('刷新')
    expect(viewport.scrollTop).toBe(120)
    wrapper.unmount()
  })

  it('手动刷新期间使用原生禁用态但保持按钮文案与位置', async () => {
    let resolve: (value: unknown) => void = () => {}
    const load = vi.fn().mockResolvedValueOnce(snapshot(1, [actor('1', 1)])).mockImplementationOnce(() => new Promise(r => { resolve = r }))
    const wrapper = mount(NearbyPage, { props: { host: { load } } })
    const page = wrapper.vm as unknown as { update(value: unknown): void }
    page.update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    const button = wrapper.get('.nearby-refresh')
    const pending = button.trigger('click')
    await nextTick()
    expect(button.attributes('disabled')).toBeDefined()
    expect(button.text()).toBe('刷新')
    resolve(snapshot(2, [actor('1', 2)]))
    await pending
    await flushPromises()
    expect(button.attributes('disabled')).toBeUndefined()
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
    expect(wrapper.get('.nearby-count-note').text()).toContain('读取失败，请刷新重试')
    expect(wrapper.find('.nearby-empty').exists()).toBe(true)
    expect(wrapper.findAll('.nearby-card')).toHaveLength(0)
    expect(wrapper.get('.nearby-count-note').text()).toBe('读取失败，请刷新重试')
    wrapper.unmount()
  })

  it('无数据且读取失败时给出可重试的错误空态，重试复用刷新入口', async () => {
    const load = vi.fn().mockRejectedValue(new Error('网络断开'))
    const wrapper = mount(NearbyPage, { props: { host: { load, openFloating: vi.fn() } } })
    ;(wrapper.vm as unknown as { update(value: unknown): void }).update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    expect(wrapper.get('.nearby-empty h3').text()).toBe('附近数据读取失败')
    expect(wrapper.get('.nearby-empty').text()).toContain('网络断开')
    expect(wrapper.get('.nearby-empty').attributes('aria-live')).toBe('assertive')
    expect(wrapper.find('.nearby-empty .nearby-retry').exists()).toBe(true)
    await wrapper.get('.nearby-retry').trigger('click')
    await flushPromises()
    expect(load).toHaveBeenCalledTimes(2)
    expect(wrapper.get('.nearby-count-note').text()).toBe('读取失败，请刷新重试')
    wrapper.unmount()
  })

  it('观察周期推进时列表行保持同一批 DOM 节点，不整表重挂', async () => {
    const load = vi.fn()
      .mockResolvedValueOnce(snapshot(1, [actor('1', 1), actor('2', 2)]))
      .mockResolvedValueOnce({ ...snapshot(2, [actor('1', 1), actor('2', 2)]), observation_id: 2 })
    const wrapper = mount(NearbyPage, { props: { host: { load, openFloating: vi.fn() } } })
    const page = wrapper.vm as unknown as { update(value: unknown): void }
    page.update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    await nextTick()
    const cards = wrapper.findAll('.nearby-card').map(card => card.element)
    expect(cards).toHaveLength(2)
    // 同账号同场景内摘要只能带版本推进，周期编号变化不应改变行 key。
    page.update({ uid: '1', version: 2, observation_id: 1, phase: 'observing' })
    await flushPromises()
    await nextTick()
    expect(wrapper.findAll('.nearby-card').map(card => card.element)).toEqual(cards)
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
    // 自制下拉的选项面板 teleport 到 body，点击要走原生 DOM
    await wrapper.get('.nearby-sort').trigger('click')
    const sortOptions = [...document.body.querySelectorAll<HTMLButtonElement>('.ui-picker__option')]
    sortOptions.find(option => option.textContent?.includes('有牌优先'))!.click()
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

  it('搜索命中进化链中的其它形态时也返回该精灵', async () => {
    const target = { ...actor('1', 1), name: '恶魔叮', chain_names: ['恶魔叮', '叮叮恶魔', '恶魔男爵'] }
    const other = { ...actor('2', 2), name: '迪莫', chain_names: ['迪莫'] }
    const load = vi.fn().mockResolvedValueOnce(snapshot(1, [target, other]))
    const wrapper = mount(NearbyPage, { props: { host: { load, openFloating: vi.fn() } } })
    ;(wrapper.vm as unknown as { update(value: unknown): void }).update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    await nextTick()
    await wrapper.get('input[type="search"]').setValue('恶魔男爵')
    await nextTick()
    expect(wrapper.findAll('.nearby-card').map(card => card.attributes('id'))).toEqual(['nearby-actor-1'])
    wrapper.unmount()
  })

})

describe('附近精灵提醒音开关', () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('nearby-list-pane') ? 680 : 220
    })
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(640)
  })
  afterEach(() => vi.restoreAllMocks())

  it('壳层提供 alert 时开关同步 aria-pressed、文案与 toggle 目标值', async () => {
    const toggle = vi.fn((next?: boolean) => next ?? true)
    const host = { load: vi.fn().mockResolvedValue(snapshot(1, [])), alert: { enabled: () => true, toggle } }
    const wrapper = mount(NearbyPage, { props: { host } })
    const button = wrapper.get('.nearby-toolbar .nearby-alert')
    expect(button.attributes('aria-pressed')).toBe('true')
    expect(button.text()).toBe('提醒音开')
    expect(button.attributes('title')).toContain('点击关闭')
    await button.trigger('click')
    expect(toggle).toHaveBeenCalledWith(false)
    expect(button.attributes('aria-pressed')).toBe('false')
    expect(button.text()).toBe('提醒音关')
    expect(button.attributes('title')).toContain('点击开启')
    wrapper.unmount()
  })

  it('壳层未提供 alert 时不渲染开关，既有工具条按钮次序不变', () => {
    const host = { load: vi.fn().mockResolvedValue(snapshot(1, [])) }
    const wrapper = mount(NearbyPage, { props: { host } })
    expect(wrapper.find('.nearby-alert').exists()).toBe(false)
    expect(wrapper.findAll('.nearby-toolbar > button:not(.ui-picker)').map(item => item.text())).toEqual(['刷新', '悬浮雷达'])
    wrapper.unmount()
  })
})

const MAP_CATALOG = {
  schema_version: 1,
  coordinate_version: 1,
  maps: {
    '10003': {
      name: '卡洛西亚大陆', availability: 'supported',
      image: { url: '/static/maps/10003.webp', width: 4096, height: 4096 },
      projection: { origin_x: 306000, origin_y: 408000, side: 408000 },
      calibration: { level: 'verified' },
    },
    '10018': {
      name: '魔法学院', availability: 'candidate',
      image: { url: '/static/maps/10018.webp', width: 4096, height: 4096 },
      projection: { origin_x: -886161, origin_y: -891000, side: 180000 },
      calibration: { level: 'candidate' },
    },
  },
}

function mappedSnapshot(version: number, resourceId: string, actors: NearbyActor[] = [actor('1', version)]) {
  return { ...snapshot(version, actors), resource_id: resourceId, instance_id: '42' }
}

function coverageSnapshot(version: number, cells = 3) {
  const coverage = {
    uid: '1', map_id: '10003', layer: 'visit' as const, scope: 'session' as const,
    revision: 1, cell_size: 2000, cells, rows: [[210, 160, cells]] as [number, number, number][],
  }
  return { ...mappedSnapshot(version, '10003'), coverage }
}

describe('附近精灵地图模式', () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('nearby-list-pane') ? 680 : 220
    })
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(640)
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('可用地图自动显示，未知场景回退雷达，切回可用场景恢复地图', async () => {
    const load = vi.fn().mockResolvedValueOnce(mappedSnapshot(1, '10003'))
      .mockResolvedValueOnce({ ...mappedSnapshot(2, '10018'), observation_id: 2 })
      .mockResolvedValueOnce({ ...mappedSnapshot(3, '10003'), observation_id: 3 })
    const wrapper = mount(NearbyPage, { props: { host: { load, loadMaps: vi.fn().mockResolvedValue(MAP_CATALOG) } } })
    const page = wrapper.vm as unknown as { update(value: unknown): void }
    page.update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    expect(wrapper.find('.scene-map').exists()).toBe(true)
    expect(wrapper.find('.scene-radar').exists()).toBe(false)
    page.update({ uid: '1', version: 2, observation_id: 2, phase: 'observing' })
    await flushPromises()
    expect(wrapper.find('.scene-map').exists()).toBe(false)
    expect(wrapper.find('.scene-radar').exists()).toBe(true)
    page.update({ uid: '1', version: 3, observation_id: 3, phase: 'observing' })
    await flushPromises()
    expect(wrapper.find('.scene-map').exists()).toBe(true)
    wrapper.unmount()
  })

  it('地图清单失败时显示雷达并可重试', async () => {
    const loadMaps = vi.fn().mockRejectedValueOnce(new Error('失败')).mockResolvedValue(MAP_CATALOG)
    const wrapper = mount(NearbyPage, { props: { host: { load: vi.fn().mockResolvedValue(mappedSnapshot(1, '10003')), loadMaps } } })
    ;(wrapper.vm as unknown as { update(value: unknown): void }).update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    expect(wrapper.find('.scene-radar').exists()).toBe(true)
    await wrapper.findAll('button').find(button => button.text().includes('重试地图清单'))!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.scene-map').exists()).toBe(true)
    wrapper.unmount()
  })

  it('停止采集时保留历史覆盖但清除精灵和人物位置', async () => {
    const load = vi.fn().mockResolvedValueOnce(coverageSnapshot(1)).mockResolvedValueOnce({
      ...snapshot(2, []), phase: 'stopped', observation_id: 2, resource_id: null, instance_id: null,
      player_position: null, coverage: null,
    })
    const wrapper = mount(NearbyPage, { props: { host: { load, loadMaps: vi.fn().mockResolvedValue(MAP_CATALOG) } } })
    const page = wrapper.vm as unknown as { update(value: unknown): void }
    page.update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    page.update({ uid: '1', version: 2, observation_id: 2, phase: 'stopped' })
    await flushPromises()
    const mapData = wrapper.getComponent(SceneMap).props('data')
    expect(mapData?.coverage?.cells).toBe(3)
    expect(mapData?.actors).toEqual([])
    expect(mapData?.player_position).toBeNull()
    wrapper.unmount()
  })

  it('页头显示当前观察账号，切号后更新为新账号', async () => {
    const load = vi.fn()
      .mockResolvedValueOnce(snapshot(1, [actor('1', 1)]))
      .mockResolvedValueOnce({ ...snapshot(1, [actor('2', 2)]), uid: '123456789012345' })
    const wrapper = mount(NearbyPage, { props: { host: { load } } })
    const page = wrapper.vm as unknown as { update(value: unknown): void }
    page.update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    expect(wrapper.get('.nearby-account').text()).toBe('账号 1')
    expect(wrapper.get('.nearby-account').attributes('title')).toContain('当前观察账号 1')
    page.update({ uid: '123456789012345', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    expect(wrapper.get('.nearby-account').text()).toMatch(/^账号 …\d{9}$/)
    expect(wrapper.get('.nearby-account').attributes('title')).toContain('123456789012345')
    wrapper.unmount()
  })

  it('壳层没有清除接口时不渲染清除足迹按钮，有接口但无足迹时禁用', async () => {
    const plain = mount(NearbyPage, { props: { host: { load: vi.fn().mockResolvedValue(coverageSnapshot(1)) } } })
    ;(plain.vm as unknown as { update(value: unknown): void }).update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    expect(plain.find('.nearby-clear-coverage').exists()).toBe(false)
    plain.unmount()

    const empty = mount(NearbyPage, { props: { host: { load: vi.fn().mockResolvedValue(mappedSnapshot(1, '10003')), resetCoverage: vi.fn() } } })
    ;(empty.vm as unknown as { update(value: unknown): void }).update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    const button = empty.get('.nearby-clear-coverage')
    expect(button.text()).toBe('清除足迹')
    expect(button.attributes('disabled')).toBeDefined()
    empty.unmount()
  })

  it('清除足迹后刷新快照确认服务端已清空', async () => {
    const resetCoverage = vi.fn().mockResolvedValue({ ok: true })
    const load = vi.fn()
      .mockResolvedValueOnce(coverageSnapshot(1))
      .mockResolvedValueOnce({ ...mappedSnapshot(2, '10003'), coverage: null })
    const wrapper = mount(NearbyPage, {
      props: { host: { load, loadMaps: vi.fn().mockResolvedValue(MAP_CATALOG), resetCoverage } },
    })
    ;(wrapper.vm as unknown as { update(value: unknown): void }).update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    expect(wrapper.get('.nearby-count-note').text()).not.toContain('清除足迹失败')
    expect(wrapper.find('.scene-map').exists()).toBe(true)
    const button = wrapper.get('.nearby-clear-coverage')
    expect(button.attributes('disabled')).toBeUndefined()
    await button.trigger('click')
    await flushPromises()
    expect(resetCoverage).toHaveBeenCalledTimes(1)
    expect(resetCoverage).toHaveBeenCalledWith({ uid: '1', resource_id: '10003', observation_id: 1 })
    expect(load).toHaveBeenCalledTimes(2)
    expect(wrapper.find('.map-coverage').exists()).toBe(false)
    expect(wrapper.get('.nearby-clear-coverage').attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('.nearby-card')).toHaveLength(1)
    wrapper.unmount()
  })

  it('清除失败时重新读取并给出重试提示', async () => {
    const resetCoverage = vi.fn().mockRejectedValue(new Error('服务不可用'))
    const load = vi.fn().mockResolvedValue(coverageSnapshot(1))
    const wrapper = mount(NearbyPage, {
      props: { host: { load, loadMaps: vi.fn().mockResolvedValue(MAP_CATALOG), resetCoverage } },
    })
    ;(wrapper.vm as unknown as { update(value: unknown): void }).update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    const button = wrapper.get('.nearby-clear-coverage')
    await button.trigger('click')
    await flushPromises()
    expect(resetCoverage).toHaveBeenCalledTimes(1)
    expect(load).toHaveBeenCalledTimes(2)
    expect(wrapper.find('.scene-map').exists()).toBe(true)
    expect(button.attributes('disabled')).toBeUndefined()
    expect(wrapper.get('.nearby-count-note').text()).toBe('清除足迹失败，请重试')
    expect(wrapper.get('.nearby-count-note').attributes('title')).toContain('服务不可用')
    wrapper.unmount()
  })

  it('清除期间切号后旧请求失败不能恢复旧账号数据', async () => {
    let rejectReset: (error: Error) => void = () => {}
    const resetCoverage = vi.fn(() => new Promise((_, reject) => { rejectReset = reject }))
    const load = vi.fn().mockResolvedValueOnce(coverageSnapshot(1))
      .mockResolvedValueOnce({ ...mappedSnapshot(1, '10003'), uid: '2', actors: [actor('2', 1)] })
    const wrapper = mount(NearbyPage, { props: { host: { load, loadMaps: vi.fn().mockResolvedValue(MAP_CATALOG), resetCoverage } } })
    const page = wrapper.vm as unknown as { update(value: unknown): void }
    page.update({ uid: '1', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    await wrapper.get('.nearby-clear-coverage').trigger('click')
    page.update({ uid: '2', version: 1, observation_id: 1, phase: 'observing' })
    await flushPromises()
    rejectReset(new Error('超时'))
    await flushPromises()
    expect(wrapper.get('.nearby-account').text()).toBe('账号 2')
    expect(wrapper.get('.nearby-card').attributes('id')).toBe('nearby-actor-2')
    expect(load).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
})
