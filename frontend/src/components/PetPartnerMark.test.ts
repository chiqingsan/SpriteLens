import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import PetPartnerMark from './PetPartnerMark.vue'
import PetSlots from './PetSlots.vue'
import { testPet, testPets } from '../petTestData'

it('只读取并显示游戏返回的标记，没有设置交互', () => {
  const pet = testPet()
  pet.partner_mark_id = 4
  pet.partner_mark = { id: 4, name: '伙伴标记', icon_url: '/static/partner-marks/img_biaoji16_png.webp', frame_url: '/static/partner-marks/frame.webp' }
  const wrapper = mount(PetPartnerMark, { props: { pet } })
  expect(wrapper.find('.pet-partner-mark').exists()).toBe(true)
  expect(wrapper.find('.pet-partner-mark-frame').attributes('src')).toBe('/static/partner-marks/frame.webp')
  expect(wrapper.find('.pet-partner-mark-icon').attributes('src')).toBe('/static/partner-marks/img_biaoji16_png.webp')
  expect(wrapper.findAll('button')).toHaveLength(0)
  wrapper.unmount()
})

it('无标记时不渲染占位图', () => {
  const wrapper = mount(PetPartnerMark, { props: { pet: testPet() } })
  expect(wrapper.find('.pet-partner-mark').exists()).toBe(false)
})

it('点阵卡片顶部顺序是 性别 → 伙伴标记 → 已有标记 → 性格', () => {
  const data = testPets(1)
  const pet = data.pets[0]!
  pet.partner_mark_id = 4
  pet.partner_mark = { id: 4, name: '伙伴标记', icon_url: '/static/partner-marks/img_biaoji16_png.webp', frame_url: '/static/partner-marks/frame.webp' }
  const wrapper = mount(PetSlots, {
    props: { slots: data.backpack.boxes[0]!.slots.slice(0, 1), pets: new Map([[pet.gid, pet]]), selected: null, teams: false, activeTeam: 0 },
  })
  const nodes = ['.pc-gender', '.pet-partner-mark', '.point-markers', '.point-nature'].map(selector => wrapper.get('.point-top ' + selector).element)
  for (let index = 1; index < nodes.length; index++) {
    expect(nodes[index - 1]!.compareDocumentPosition(nodes[index]!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  }
  expect(wrapper.get('.point-top > .point-top-left .pet-partner-mark').element).toBeTruthy()
  wrapper.unmount()
})

it('未知伙伴标记 ID 时不渲染槽位', () => {
  const data = testPets(1)
  const pet = data.pets[0]!
  pet.partner_mark_id = 2
  pet.partner_mark = null
  const wrapper = mount(PetSlots, {
    props: { slots: data.backpack.boxes[0]!.slots.slice(0, 1), pets: new Map([[pet.gid, pet]]), selected: null, teams: false, activeTeam: 0 },
  })
  expect(wrapper.find('.point-top .pet-partner-mark').exists()).toBe(false)
  wrapper.unmount()
})
