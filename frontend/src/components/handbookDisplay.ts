const FALLBACK = '#6b8188'

/** 游戏色不变；按 WCAG 相对亮度选择白/黑字，任意主题下均可读。 */
export function textColorOn(background: string): string {
  const hex = /^#[0-9a-f]{6}$/i.test(background) ? background : FALLBACK
  const channels = hex.slice(1).match(/../g)!.map(part => {
    const value = parseInt(part, 16) / 255
    return value <= 0.04045 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4)
  })
  const luminance = channels[0]! * 0.2126 + channels[1]! * 0.7152 + channels[2]! * 0.0722
  return luminance > 0.179 ? '#000000' : '#ffffff'
}

export function typeBadgeStyle(color?: string): Record<string, string> {
  const background = color && /^#[0-9a-f]{6}$/i.test(color) ? color : FALLBACK
  return { background, color: textColorOn(background) }
}
