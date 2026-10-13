import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import EggDexPage from './EggDexPage.vue'
import { dex } from '../testData'

it('安全插值、键盘详情、焦点返回、重复挂载与卸载清理', async () => {
  vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  const api = vi.fn().mockResolvedValue({ ...dex, eggs: [{ ...dex.eggs[0], egg_name: '<img onerror=alert(1)>' }] })
  const wrapper = mount(EggDexPage, { props: { api }, attachTo: document.body })
  await flushPromises()
  const card = wrapper.get('.hb-card')
  expect(card.text()).toContain('<img onerror=alert(1)>')
  expect(card.find('strong img').exists()).toBe(false)
  await card.trigger('keydown', { key: 'Enter' })
  expect(wrapper.get('[role="dialog"]').text()).toContain('暂无数据')
  const content = wrapper.get('.content-panel').element
  expect(content instanceof HTMLElement && content.inert).toBe(true)
  expect(document.activeElement).toBe(wrapper.get('.detail-close').element)
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  await flushPromises()
  expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  expect(document.activeElement).toBe(card.element)
  await card.trigger('click')
  wrapper.unmount()
  const second = mount(EggDexPage, { props: { api } })
  await flushPromises()
  expect(api).toHaveBeenCalledTimes(2)
  expect(second.find('[role="dialog"]').exists()).toBe(false)
  second.unmount()
  vi.unstubAllGlobals()
})
