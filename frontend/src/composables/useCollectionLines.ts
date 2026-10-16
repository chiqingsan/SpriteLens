import { ref, shallowRef } from 'vue'
import { parseCollectionLines } from '../types/collectionLines'

export const collectionGoals = [
  ['big-soft', '大块头 · 婉转声'], ['big-loud', '大块头 · 粗嗓门'],
  ['small-soft', '小不点 · 婉转声'], ['small-loud', '小不点 · 粗嗓门'],
] as const
export interface CollectionSettings {
  goal: string; sound: string; full_weight: boolean; colorful: boolean; ignore_missing_male: boolean
}
export interface CollectionHost {
  load: (settings: CollectionSettings) => Promise<unknown | null>
  cancel: () => void
  uid: () => number | null
  openPet: (gid: string) => void
}
const defaults = (): CollectionSettings => ({ goal: 'big-soft', sound: '', full_weight: false, colorful: false, ignore_missing_male: false })

export function useCollectionLines(host: CollectionHost) {
  const data = shallowRef<ReturnType<typeof parseCollectionLines> | null>(null)
  const settings = ref(defaults())
  const loading = ref(false), error = ref(''), saveError = ref('')
  let generation = 0, settingsUid: number | null = null

  function readSettings() {
    const uid = host.uid()
    if (uid === settingsUid) return
    settingsUid = uid
    settings.value = defaults()
    saveError.value = ''
    if (!uid) return
    try {
      const saved: unknown = JSON.parse(localStorage.getItem(`spritelens.collection.${uid}`) || 'null')
      if (saved && typeof saved === 'object' && 'goal' in saved && 'sound' in saved
        && 'full_weight' in saved && 'colorful' in saved && 'ignore_missing_male' in saved
        && collectionGoals.some(([key]) => key === saved.goal) && ['', '100', '-100'].includes(String(saved.sound))
        && typeof saved.full_weight === 'boolean' && typeof saved.colorful === 'boolean' && typeof saved.ignore_missing_male === 'boolean') {
        settings.value = { goal: String(saved.goal), sound: String(saved.sound), full_weight: saved.full_weight,
          colorful: saved.colorful, ignore_missing_male: saved.ignore_missing_male }
      }
    } catch (cause) { saveError.value = `目标偏好读取失败：${cause instanceof Error ? cause.message : String(cause)}` }
  }
  async function load() {
    readSettings()
    const current = ++generation
    loading.value = true
    error.value = ''
    try {
      const payload = await host.load({ ...settings.value })
      if (current !== generation || payload === null) return
      data.value = parseCollectionLines(payload)
    } catch (cause) {
      if (current === generation) error.value = cause instanceof Error ? cause.message : String(cause)
    } finally { if (current === generation) loading.value = false }
  }
  async function apply() {
    saveError.value = ''
    try {
      if (settingsUid) localStorage.setItem(`spritelens.collection.${settingsUid}`, JSON.stringify(settings.value))
    } catch (cause) { saveError.value = `目标未保存，下次启动需重新设置：${cause instanceof Error ? cause.message : String(cause)}` }
    await load()
  }
  function pause() { ++generation; host.cancel(); loading.value = false }
  function resetAccount() { pause(); data.value = null; error.value = ''; settingsUid = null; settings.value = defaults() }
  return { data, settings, loading, error, saveError, load, apply, pause, resetAccount }
}
