import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EggDexPage from './EggDexPage.vue'
import { dex } from '../testData'

const originalMatchMedia = window.matchMedia
const dialogPrototype = window.HTMLDialogElement?.prototype as (HTMLDialogElement & {
  showModal?: () => void
  close?: () => void
}) | undefined

if (dialogPrototype && !dialogPrototype.showModal) dialogPrototype.showModal = function showModal(this: HTMLDialogElement) { this.open = true }
if (dialogPrototype && !dialogPrototype.close) dialogPrototype.close = function close(this: HTMLDialogElement) { this.open = false }

beforeEach(() => {
  HTMLElement.prototype.scrollTo = vi.fn()
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: (query: string) => ({ matches: false, media: query, onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() }),
  })
})
afterEach(() => { Object.defineProperty(window, 'matchMedia', { configurable: true, value: originalMatchMedia }) })

function pageRows(count: number) {
  return Array.from({ length: count }, (_, index) => ({ ...dex.eggs[0], egg_conf_id: 3001001 + index,
    egg_name: `测试蛋${index + 1}`, handbook_no: String(index + 2).padStart(3, '0'),
    egg_group_names: index % 2 ? ['动物组', '拟人组'] : ['动物组'], can_same_ride: index % 3 !== 0 }))
}

describe('蛋蛋图鉴页面布局契约', () => {
  it('固定每页30枚，顶部提供页码条，卡片编号放在左上角且不显示额外摘要', async () => {
    const rows = pageRows(31)
    const api = vi.fn().mockResolvedValue({ ...dex, total: rows.length, shown: rows.length, eggs: rows })
    const wrapper = mount(EggDexPage, { props: { api, active: true } })
    await flushPromises()

    expect(wrapper.find('.box-total').text()).toContain('每页 30 枚')
    expect(wrapper.findAll('#ed-grid > button')).toHaveLength(30)
    expect(wrapper.findAll('.dex-page-navigation')).toHaveLength(1)
    expect(wrapper.find('.dex-pager').exists()).toBe(false)
    expect(wrapper.findAll('.dex-card-number')).toHaveLength(30)
    expect(wrapper.find('.dex-card-number').text()).toBe('No.002 · 普通')
    expect(wrapper.find('.dex-card-summary').exists()).toBe(false)
    expect(wrapper.find('.dex-card-groups').text()).not.toContain('同乘')
    expect(wrapper.find('#ed-grid').text()).not.toContain('蛋#')
    wrapper.unmount()
  })

  it('工具栏只保留主要筛选，更多筛选承载其余选项并用固定图标占位', async () => {
    const api = vi.fn().mockResolvedValue({ ...dex, total: 1, shown: 1, eggs: pageRows(1) })
    const wrapper = mount(EggDexPage, { props: { api, active: true } })
    await flushPromises()

    expect(wrapper.find('#ed-search').exists()).toBe(true)
    expect(wrapper.findAll('.dex-toolbar-actions > .dex-filter-button')).toHaveLength(3)
    expect(wrapper.find('.dex-more-filter-trigger').text()).toContain('更多筛选')
    expect(wrapper.find('.dex-more-filter-dialog').text()).toContain('排序')
    expect(wrapper.find('.dex-more-filter-dialog').text()).toContain('组别')
    expect(wrapper.find('.dex-more-filter-dialog').text()).toContain('同乘')
    expect(wrapper.findAll('.dex-more-filter-options .ui-icon')).toHaveLength(8)
    expect(wrapper.find('.dex-more-filter-dialog').text()).not.toMatch(/[✓✔✕×↗→]/)
    wrapper.unmount()
  })
})
