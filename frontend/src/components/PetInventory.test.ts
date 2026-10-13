import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { expect, it, vi } from 'vitest'
import PetInventory from './PetInventory.vue'
import { usePets } from '../composables/usePets'
import { testPets } from '../petTestData'

it('安全文本、键盘选择与数据更新保留焦点', async () => {
  vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  document.body.innerHTML = '<section id="page-pets"><div class="workspace split"><div id="pet-detail-root"></div></div></section><div id="pet-view"></div><div id="pet-count-root"></div>'
  const model = usePets(vi.fn(), () => ({ uid: 101, version: 10, generation: 1 }), () => ({}), vi.fn(), vi.fn())
  const payload = testPets()
  payload.pets[0]!.name = '<img onerror=alert(1)>'
  model.accept(payload)
  const wrapper = mount(PetInventory, { props: { model, imageMode: () => 'portrait' }, attachTo: document.body })
  try {
    expect(wrapper.find('.point-name img').exists()).toBe(false)
    const count = document.getElementById('pet-count')!
    const previousCount = count.textContent
    model.busy.value = true; await nextTick()
    expect(count.textContent).toBe(previousCount)
    model.busy.value = false
    model.setView('card'); await nextTick()
    const card = wrapper.get('.pet-card'); (card.element as HTMLElement).focus()
    await card.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select')?.[0]?.[0]).toBe(1)
    model.accept(payload); await nextTick()
    expect(document.activeElement).toBe(card.element)
  } finally { wrapper.unmount(); model.pause(); document.body.innerHTML = '' }
})
