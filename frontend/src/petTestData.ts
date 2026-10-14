import { initialMeasurementLimits } from './types/petFilters'
import type { Pet, Pets } from './types/pets'
export function testPet(gid = 1): Pet {
  return { gid, name: '合成精灵 ' + gid, level: 40, gender: 1, nature_name: '性格', nature_positive: null,
    nature_negative: null, dex_no: 1, species_name: '物种', talent_rank: 2, talent_color: '#6b8188',
    type_names: ['火'], type_colors: ['#ff4400'], egg_groups: ['动物组'], stats: [],
    height_text: '1.00 m', weight_text: '2.00 kg', voice_text: '+10', height_pct: .5, weight_pct: 0, voice_pct: .1,
    range_positions: { height: { ratio: .5, status: 'within' }, weight: { ratio: null, status: 'missing' } },
    skills: [], portrait_url: '/static/pet-media/3001-normal-portrait.webp', artwork_url: '', icon_url: '', is_shiny: false,
    is_colorful: false, color_card: null, medal_marks: [], base_conf_id: 3004, stat_sum: 0, species_stat_sum: 0,
    worn_medal_id: 0, catch_way: 0, add_time: 0, worn_medal_name: '', location: null, reference_ranges: { height: '暂无数据', weight: '暂无数据' }, egg_ranges: { height: '暂无数据', weight: '暂无数据' },
    detail: { speciality_name: '特性未知', acquisition_name: '未采集', types: [],
      measurements: { height: { value: 1, limits: [.5, 1.5], ratio: .5, status: 'within' },
        weight: { value: 2, limits: null, ratio: null, status: 'unknown' }, voice: { value: 10, limits: [-100, 100], ratio: .55, status: 'within' } },
      egg_limits: { height: null, weight: null }, evolution: { nodes: [], edges: [] }, awarded_medals: null } }
}
export function testPets(count = 1): Pets {
  return { uid: 101, version: 10, total: count, shown: count,
    pets: Array.from({ length: count }, (_, index) => testPet(index + 1)), filters: {},
    options: { natures: [], types: ['火'], sorts: [{ key: 'dex_no', label: '图鉴 ID' }, { key: 'add_time', label: '捕捉时间' },
      { key: 'level', label: '等级' }, { key: 'height', label: '身高' }, { key: 'weight', label: '体重' }, { key: 'voice', label: '声音' }],
      talent_max: 2, measurement_limits: initialMeasurementLimits, egg_groups: ['动物组'] },
    backpack: { boxes: count ? [{ box_id: 1, name: '合成箱', historical: true, matched: 1, occupied: 2, unknown: 1,
      slots: [{ gid: 1, state: 'matched' }, { gid: 999, state: 'missing' }, { gid: null, state: 'unknown' },
        ...Array.from({ length: 27 }, () => ({ gid: 0, state: 'empty' as const }))] }] : [],
      teams: [], active_team: 0, filtering: false, unlocated_total: Math.max(0, count - 1), unlocated_shown: Math.max(0, count - 1) } }
}
