import type { Pet } from '../types/pets'

export function gender(pet: Pet) { return pet.gender === 2 ? 'female' : pet.gender === 1 ? 'male' : '' }
export function genderMark(pet: Pet) { return pet.gender === 2 ? '♀' : pet.gender === 1 ? '♂' : '—' }
export function badgeStyle(color: string) {
  const valid = /^#[0-9a-f]{6}$/i.test(color) ? color : '#6b8188'
  const rgb = valid.slice(1).match(/../g)!.map(part => {
    const value = parseInt(part, 16) / 255
    return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4
  })
  return { background: valid, color: rgb[0]! * .2126 + rgb[1]! * .7152 + rgb[2]! * .0722 > .179 ? '#000000' : '#ffffff' }
}
export function positionText(pet: Pet, field: 'height' | 'weight') {
  const position = pet.range_positions[field]
  return position.ratio === null ? '暂无范围' : position.status !== 'within' ? '超出范围' : (position.ratio * 100).toFixed(1) + '%'
}
export function pointValue(pet: Pet, field: 'height' | 'weight' | 'voice') {
  if (field === 'voice') return pet.voice_text === '暂无数据' ? '—' : pet.voice_text
  const position = pet.range_positions[field]
  return position.ratio === null ? '—' : position.status !== 'within' ? '超界' :
    (position.ratio === 0 || position.ratio === 1 ? position.ratio * 100 : (position.ratio * 100).toFixed(1)) + '%'
}
