<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import UiIcon from './UiIcon.vue'

/** 选项既支持 { value, label }，也支持裸字符串 / 数字，迁移原生 select 时少写样板。 */
export interface UiSelectOption {
  value: string | number | null
  label: string
  hint?: string
}

type RawOption = UiSelectOption | string | number

const props = withDefaults(
  defineProps<{
    modelValue?: string | number | null
    options: RawOption[]
    /** 无障碍名称；没有对应 <label> 时必填。 */
    label?: string
    placeholder?: string
    disabled?: boolean
    /** md 34px（表单默认）/ sm 30px / xs 28px（紧凑行内）。 */
    size?: 'md' | 'sm' | 'xs'
  }>(),
  {
    modelValue: null,
    label: undefined,
    placeholder: '请选择',
    disabled: false,
    size: 'md',
  },
)

const emit = defineEmits<{
  (event: 'update:modelValue', value: string | number | null): void
  (event: 'change', value: string | number | null): void
}>()

const items = computed<UiSelectOption[]>(() =>
  props.options.map(option =>
    option !== null && typeof option === 'object' ? option : { value: option, label: String(option) },
  ),
)

const trigger = ref<HTMLButtonElement | null>(null)
const panel = ref<HTMLDivElement | null>(null)
const open = ref(false)
const active = ref(-1)
const dropUp = ref(false)
const panelStyle = ref<Record<string, string>>({})
const teleportTo = ref<string | HTMLElement>('body')
const dialogHost = ref<HTMLDialogElement | null>(null)
const uid = 'ui-picker-' + Math.random().toString(36).slice(2, 9)

const selectedIndex = computed(() => items.value.findIndex(option => option.value === props.modelValue))
const current = computed(() => (selectedIndex.value >= 0 ? items.value[selectedIndex.value] : null))
const display = computed(() => current.value?.label ?? props.placeholder)

/** 弹层用 fixed 定位：宿主面板几乎都是 overflow:auto，容器内 absolute 会被裁掉。 */
function place() {
  const el = trigger.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const gap = 4
  const below = window.innerHeight - rect.bottom - gap
  const panelHeight = panel.value?.offsetHeight ?? 0
  dropUp.value = below < Math.min(panelHeight, 240) && rect.top > below
  const width = Math.max(rect.width, 148)
  const maxWidth = Math.min(340, window.innerWidth - 16)
  const shownWidth = Math.min(width, maxWidth)
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - shownWidth - 8))
  const available = dropUp.value ? rect.top - 12 : below
  const style: Record<string, string> = {
    left: Math.round(left) + 'px',
    minWidth: Math.round(shownWidth) + 'px',
    maxWidth: Math.round(maxWidth) + 'px',
    maxHeight: Math.round(Math.max(132, Math.min(320, available))) + 'px',
  }
  if (dropUp.value) style.bottom = Math.round(window.innerHeight - rect.top + gap) + 'px'
  else style.top = Math.round(rect.bottom + gap) + 'px'
  panelStyle.value = style
}

function onOutside(event: PointerEvent) {
  const target = event.target as Node | null
  if (!target) return
  if (trigger.value?.contains(target) || panel.value?.contains(target)) return
  closePanel()
}

function onViewportChange() {
  place()
}

function openPanel() {
  if (props.disabled || open.value) return
  const el = trigger.value
  if (!el) return
  // 原生 <dialog> 在 top layer，弹层必须挂在它内部，否则会被盖住。
  dialogHost.value = el.closest('dialog')
  teleportTo.value = dialogHost.value ?? document.body
  // 弹窗被程序关闭时（不经过 pointerdown）也要收掉弹层，否则重新打开弹窗会看到残留面板。
  dialogHost.value?.addEventListener('close', closePanel)
  open.value = true
  active.value = selectedIndex.value >= 0 ? selectedIndex.value : 0
  nextTick(() => {
    place()
    nextTick(() => {
      place()
      scrollActive()
    })
  })
  document.addEventListener('pointerdown', onOutside, true)
  window.addEventListener('resize', onViewportChange)
  window.addEventListener('scroll', onViewportChange, true)
}

function closePanel() {
  dialogHost.value?.removeEventListener('close', closePanel)
  dialogHost.value = null
  if (!open.value) return
  open.value = false
  active.value = -1
  document.removeEventListener('pointerdown', onOutside, true)
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
}

function scrollActive() {
  const el = panel.value?.querySelector<HTMLElement>('[data-index="' + active.value + '"]')
  el?.scrollIntoView({ block: 'nearest' })
}

function choose(index: number) {
  const option = items.value[index]
  if (!option) return
  if (option.value !== props.modelValue) {
    emit('update:modelValue', option.value)
    emit('change', option.value)
  }
  closePanel()
  trigger.value?.focus()
}

function move(delta: number) {
  const count = items.value.length
  if (!count) return
  active.value = (Math.max(active.value, 0) + delta + count) % count
  scrollActive()
}

function onKeydown(event: KeyboardEvent) {
  if (props.disabled) return
  const key = event.key
  if (!open.value) {
    if (key === 'ArrowDown' || key === 'ArrowUp' || key === 'Enter' || key === ' ') {
      event.preventDefault()
      openPanel()
    }
    return
  }
  if (key === 'ArrowDown') {
    event.preventDefault()
    move(1)
  } else if (key === 'ArrowUp') {
    event.preventDefault()
    move(-1)
  } else if (key === 'Home') {
    event.preventDefault()
    active.value = 0
    scrollActive()
  } else if (key === 'End') {
    event.preventDefault()
    active.value = items.value.length - 1
    scrollActive()
  } else if (key === 'Enter' || key === ' ') {
    event.preventDefault()
    choose(active.value)
  } else if (key === 'Escape' || key === 'Tab') {
    closePanel()
  }
}

watch(
  () => props.disabled,
  value => {
    if (value) closePanel()
  },
)

onBeforeUnmount(closePanel)
</script>

<template>
  <button
    ref="trigger"
    type="button"
    class="ui-picker"
    :class="['ui-picker--' + size, { 'is-open': open, 'is-empty': !current }]"
    role="combobox"
    aria-haspopup="listbox"
    :aria-label="label"
    :aria-expanded="open"
    :aria-controls="open ? uid + '-list' : undefined"
    :aria-activedescendant="open && active >= 0 ? uid + '-' + active : undefined"
    :disabled="disabled"
    @click="open ? closePanel() : openPanel()"
    @keydown="onKeydown"
  >
    <span class="ui-picker__label">{{ display }}</span>
    <UiIcon name="chevron-down" class="ui-picker__chevron" />
    <Teleport :to="teleportTo">
      <div v-if="open" ref="panel" class="ui-picker__panel" :class="{ 'is-up': dropUp }" :style="panelStyle">
        <div :id="uid + '-list'" class="ui-picker__list" role="listbox" :aria-label="label">
          <button
            v-for="(option, index) in items"
            :id="uid + '-' + index"
            :key="String(option.value)"
            type="button"
            role="option"
            tabindex="-1"
            class="ui-picker__option"
            :class="{ 'is-active': index === active, 'is-selected': option.value === modelValue }"
            :aria-selected="option.value === modelValue"
            :data-index="index"
            @pointerenter="active = index"
            @click="choose(index)"
          >
            <span class="ui-picker__option-label">{{ option.label }}</span>
            <span v-if="option.hint" class="ui-picker__option-hint">{{ option.hint }}</span>
            <UiIcon v-if="option.value === modelValue" name="circle-check" class="ui-picker__check" />
          </button>
          <p v-if="!items.length" class="ui-picker__empty">没有可选项</p>
        </div>
      </div>
    </Teleport>
  </button>
</template>
