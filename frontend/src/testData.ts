import type { EggDex } from './types/eggDex'
export const dex: EggDex = {
  total: 1, shown: 1, groups: ['动物组'], egg_types: ['普通'],
  eggs: [{ egg_conf_id: 3001001, base_id: 3001, egg_name: '喵喵蛋', name: '喵喵',
    icon_url: '/static/pet-media/3001-normal-portrait.webp', egg_icon_url: '/static/egg-icons/107001.webp',
    handbook_no: '002', egg_type_name: '普通', hatch_label: '12小时', hatch_seconds: 43200,
    egg_group_names: ['动物组'], gender_male: 0, gender_female: 0,
    reference_ranges: { height: '暂无数据', weight: '暂无数据' }, chain: [3001], chain_names: {} }],
}
