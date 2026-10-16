import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CollectionParentCard from './CollectionParentCard.vue'
import type { CollectionParent } from '../types/collectionLines'

const parent: CollectionParent = { gid: '9518406239959121931', name: '熔岩布丁', gender: 1, nature: '固执',
  voice: 100, basis: ['旧说明：满身高，配种参考等价大块头', '婉转声（数值参考）'],
  marks: [{ name: '婉转声', source: 'reference' }], height_ratio: 1, weight_ratio: .89,
  icon_url: '', location: null }

describe('亲本标记来源', () => {
  it('只渲染结构化标记，说明中提及大块头也不生成奖牌图标', async () => {
    const wrapper = mount(CollectionParentCard, { props: { parent } })
    expect(wrapper.find('img[alt="大块头"]').exists()).toBe(false)
    expect(wrapper.get('img[alt="婉转声"]').attributes('title')).toContain('非奖牌确认')
    expect(wrapper.text()).toContain('高 100%')
    expect(wrapper.text()).toContain('重 89%')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('open')).toEqual([[parent.gid]])
  })
})
