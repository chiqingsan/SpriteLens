import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import MedalIcon from './MedalIcon.vue'

describe('MedalIcon', () => {
  it('把奖牌名映射到本地图标，并说明来源', () => {
    const wrapper = mount(MedalIcon, { props: { name: '婉转声', source: 'worn' } })

    const image = wrapper.get('img')
    expect(image.attributes('src')).toBe('/static/medal-icons/1026.webp')
    expect(image.attributes('alt')).toBe('婉转声')
    expect(image.attributes('title')).toContain('当前佩戴')
  })

  it('未知奖牌名退化为文字，不显示破图', () => {
    const wrapper = mount(MedalIcon, { props: { name: '未知奖牌' } })

    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toBe('未知奖牌')
  })
})
