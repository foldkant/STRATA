<script setup lang="ts">
import {
  Comment,
  Fragment,
  Text,
  computed,
  nextTick,
  onBeforeUnmount,
  ref,
  useAttrs,
  useId,
  useSlots,
  type CSSProperties,
  type VNode
} from 'vue'

defineOptions({
  inheritAttrs: false
})

type SelectValue = string | number | boolean | null | undefined

interface SelectOption {
  key: string
  value: SelectValue
  label: string
  disabled: boolean
  description: string
}

const props = withDefaults(defineProps<{
  modelValue?: SelectValue
  value?: SelectValue
  disabled?: boolean
  required?: boolean
  name?: string
  placeholder?: string
  modelModifiers?: { number?: boolean }
}>(), {
  disabled: false,
  required: false,
  name: '',
  placeholder: '请选择',
  modelModifiers: () => ({})
})

const emit = defineEmits<{
  'update:modelValue': [value: SelectValue]
  change: [event: Event]
  input: [event: Event]
}>()

const attrs = useAttrs()
const slots = useSlots()
const componentId = useId().replace(/:/g, '')
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const nativeSelect = ref<HTMLSelectElement | null>(null)
const open = ref(false)
const activeIndex = ref(-1)
const previewIndex = ref(-1)
const invalid = ref(false)
const menuStyle = ref<CSSProperties>({})

function vnodeText(node: VNode | string | number | null | undefined): string {
  if (node === null || node === undefined) return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (node.type === Comment) return ''
  if (node.type === Text) return String(node.children ?? '')
  if (typeof node.children === 'string') return node.children
  if (Array.isArray(node.children)) return node.children.map((child) => vnodeText(child as VNode)).join('')
  return ''
}

function collectOptions(nodes: VNode[], rows: SelectOption[]) {
  for (const node of nodes) {
    if (node.type === Comment) continue
    if (node.type === Fragment && Array.isArray(node.children)) {
      collectOptions(node.children as VNode[], rows)
      continue
    }
    if (node.type !== 'option') continue

    const label = vnodeText(node).trim()
    const optionProps = node.props || {}
    const value = Object.prototype.hasOwnProperty.call(optionProps, 'value')
      ? optionProps.value as SelectValue
      : label
    rows.push({
      key: String(node.key ?? `${rows.length}-${String(value)}`),
      value,
      label,
      disabled: optionProps.disabled === true || optionProps.disabled === '',
      description: String(optionProps.title ?? optionProps['data-description'] ?? '').trim()
    })
  }
}

const options = computed(() => {
  const rows: SelectOption[] = []
  collectOptions(slots.default?.() || [], rows)
  return rows
})

const currentValue = computed<SelectValue>(() => (
  props.modelValue !== undefined ? props.modelValue : props.value
))

function valuesMatch(left: SelectValue, right: SelectValue) {
  if (Object.is(left, right)) return true
  if (left === null || left === undefined || right === null || right === undefined) return false
  return String(left) === String(right)
}

const selectedIndex = computed(() => options.value.findIndex((item) => valuesMatch(item.value, currentValue.value)))
const selectedOption = computed(() => options.value[selectedIndex.value] || null)
const selectedLabel = computed(() => selectedOption.value?.label || props.placeholder)
const previewOption = computed(() => options.value[previewIndex.value] || selectedOption.value)
const hasDescriptions = computed(() => options.value.some((item) => item.description))
const serializedValue = computed(() => currentValue.value === null || currentValue.value === undefined ? '' : String(currentValue.value))
const listboxId = `app-select-list-${componentId}`

const controlAttrs = computed(() => {
  const result: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'class' || key === 'style' || key === 'value') continue
    if (key.startsWith('on')) continue
    result[key] = value
  }
  return result
})

function coerceValue(value: SelectValue): SelectValue {
  if (!props.modelModifiers.number || typeof value !== 'string' || value.trim() === '') return value
  const converted = Number(value)
  return Number.isNaN(converted) ? value : converted
}

function createSelectEvent(type: 'change' | 'input', value: SelectValue) {
  return {
    type,
    target: { value },
    currentTarget: { value },
    preventDefault() {},
    stopPropagation() {}
  } as unknown as Event
}

function choose(index: number) {
  const option = options.value[index]
  if (!option || option.disabled || props.disabled) return
  const value = coerceValue(option.value)
  invalid.value = false
  emit('update:modelValue', value)
  emit('input', createSelectEvent('input', value))
  emit('change', createSelectEvent('change', value))
  closeMenu(true)
}

function nextEnabledIndex(start: number, direction: 1 | -1) {
  const rows = options.value
  if (!rows.length) return -1
  let index = start
  for (let count = 0; count < rows.length; count += 1) {
    index = (index + direction + rows.length) % rows.length
    if (!rows[index].disabled) return index
  }
  return -1
}

function firstEnabledIndex(direction: 1 | -1) {
  const start = direction === 1 ? -1 : options.value.length
  return nextEnabledIndex(start, direction)
}

function updateMenuPosition() {
  if (!open.value || !trigger.value) return
  const rect = trigger.value.getBoundingClientRect()
  const viewportGap = 8
  const menuGap = 6
  const availableBelow = window.innerHeight - rect.bottom - viewportGap - menuGap
  const availableAbove = rect.top - viewportGap - menuGap
  const preferAbove = availableBelow < 220 && availableAbove > availableBelow
  const maxHeight = Math.max(152, Math.min(420, preferAbove ? availableAbove : availableBelow))
  const desiredWidth = hasDescriptions.value ? Math.max(rect.width, 430) : Math.max(rect.width, 180)
  const width = Math.min(desiredWidth, window.innerWidth - viewportGap * 2)
  const left = Math.min(Math.max(viewportGap, rect.left), window.innerWidth - width - viewportGap)
  const measuredHeight = Math.min(menu.value?.offsetHeight || maxHeight, maxHeight)
  const top = preferAbove
    ? Math.max(viewportGap, rect.top - menuGap - measuredHeight)
    : Math.min(window.innerHeight - viewportGap - measuredHeight, rect.bottom + menuGap)

  menuStyle.value = {
    top: `${top}px`,
    left: `${left}px`,
    width: `${width}px`,
    maxHeight: `${maxHeight}px`
  }
}

function addGlobalListeners() {
  document.addEventListener('pointerdown', handleOutsidePointer, true)
  document.addEventListener('scroll', updateMenuPosition, true)
  window.addEventListener('resize', updateMenuPosition)
}

function removeGlobalListeners() {
  document.removeEventListener('pointerdown', handleOutsidePointer, true)
  document.removeEventListener('scroll', updateMenuPosition, true)
  window.removeEventListener('resize', updateMenuPosition)
}

async function openMenu() {
  if (props.disabled || !options.value.length) return
  open.value = true
  activeIndex.value = selectedIndex.value >= 0 ? selectedIndex.value : firstEnabledIndex(1)
  previewIndex.value = activeIndex.value
  addGlobalListeners()
  await nextTick()
  updateMenuPosition()
  await nextTick()
  updateMenuPosition()
  menu.value?.querySelector<HTMLElement>(`[data-option-index="${activeIndex.value}"]`)?.focus({ preventScroll: true })
}

function closeMenu(restoreFocus = false) {
  if (!open.value) return
  open.value = false
  previewIndex.value = -1
  removeGlobalListeners()
  if (restoreFocus) nextTick(() => trigger.value?.focus({ preventScroll: true }))
}

function toggleMenu() {
  if (open.value) closeMenu()
  else void openMenu()
}

function handleOutsidePointer(event: PointerEvent) {
  if (!(event.target instanceof Node)) return
  if (root.value?.contains(event.target) || menu.value?.contains(event.target)) return
  closeMenu()
}

function handleTriggerKeydown(event: KeyboardEvent) {
  if (props.disabled) return
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (!open.value) void openMenu()
    return
  }
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    toggleMenu()
  }
}

function handleOptionKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    closeMenu(true)
    return
  }
  if (event.key === 'Tab') {
    closeMenu()
    return
  }
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    choose(activeIndex.value)
    return
  }

  let targetIndex = activeIndex.value
  if (event.key === 'ArrowDown') targetIndex = nextEnabledIndex(activeIndex.value, 1)
  else if (event.key === 'ArrowUp') targetIndex = nextEnabledIndex(activeIndex.value, -1)
  else if (event.key === 'Home') targetIndex = firstEnabledIndex(1)
  else if (event.key === 'End') targetIndex = firstEnabledIndex(-1)
  else return

  event.preventDefault()
  if (targetIndex < 0) return
  activeIndex.value = targetIndex
  previewIndex.value = targetIndex
  menu.value?.querySelector<HTMLElement>(`[data-option-index="${targetIndex}"]`)?.focus({ preventScroll: true })
}

function handleInvalid(event: Event) {
  event.preventDefault()
  invalid.value = true
  trigger.value?.focus()
}

onBeforeUnmount(removeGlobalListeners)
</script>

<template>
  <div
    ref="root"
    class="app-select"
    :class="[attrs.class, { 'is-open': open, 'is-disabled': disabled, 'is-invalid': invalid }]"
    :style="attrs.style as CSSProperties"
  >
    <button
      ref="trigger"
      v-bind="controlAttrs"
      class="app-select-trigger"
      type="button"
      role="combobox"
      aria-haspopup="listbox"
      :aria-controls="listboxId"
      :aria-expanded="open"
      :aria-activedescendant="open && activeIndex >= 0 ? `${listboxId}-option-${activeIndex}` : undefined"
      :disabled="disabled"
      @click="toggleMenu"
      @keydown="handleTriggerKeydown"
    >
      <span :class="{ 'is-placeholder': !selectedOption }">{{ selectedLabel }}</span>
      <i class="app-select-chevron" aria-hidden="true"></i>
    </button>

    <select
      ref="nativeSelect"
      class="app-select-native"
      tabindex="-1"
      aria-hidden="true"
      :name="name"
      :required="required"
      :disabled="disabled"
      :value="serializedValue"
      @invalid="handleInvalid"
    >
      <option v-for="item in options" :key="item.key" :value="String(item.value ?? '')" :disabled="item.disabled">
        {{ item.label }}
      </option>
    </select>
  </div>

  <Teleport to="body">
    <Transition name="app-select-menu">
      <div
        v-if="open"
        :id="listboxId"
        ref="menu"
        class="app-select-menu"
        :class="{ 'has-descriptions': hasDescriptions }"
        :style="menuStyle"
        role="listbox"
        :aria-label="String(controlAttrs['aria-label'] || '选择选项')"
        @keydown="handleOptionKeydown"
      >
        <div class="app-select-options">
          <button
            v-for="(item, index) in options"
            :id="`${listboxId}-option-${index}`"
            :key="item.key"
            :data-option-index="index"
            class="app-select-option"
            :class="{
              'is-selected': index === selectedIndex,
              'is-active': index === activeIndex,
              'is-disabled': item.disabled
            }"
            type="button"
            role="option"
            :aria-selected="index === selectedIndex"
            :aria-disabled="item.disabled"
            :disabled="item.disabled"
            tabindex="-1"
            @mouseenter="activeIndex = index; previewIndex = index"
            @focus="activeIndex = index; previewIndex = index"
            @click="choose(index)"
          >
            <span>{{ item.label }}</span>
            <i v-if="index === selectedIndex" aria-hidden="true">✓</i>
          </button>
        </div>

        <aside v-if="hasDescriptions" class="app-select-description" aria-live="polite">
          <strong>{{ previewOption?.label || '选项说明' }}</strong>
          <span>{{ previewOption?.description || '将鼠标移到选项上查看说明。' }}</span>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.app-select {
  position: relative;
  display: block;
  width: 100%;
  min-width: 0;
  min-height: 42px;
  color: var(--text, #162033);
}

.app-select-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  min-width: 0;
  min-height: inherit;
  border: 1px solid var(--line, #d8e1ec);
  border-radius: 6px;
  background: #fff;
  padding: 0 38px 0 12px;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 160ms ease, box-shadow 160ms ease, background-color 160ms ease;
}

.app-select-trigger > span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-select-trigger > span.is-placeholder {
  color: #7a8799;
}

.app-select-trigger:hover:not(:disabled) {
  border-color: #9eb2cb;
}

.app-select-trigger:focus-visible,
.app-select.is-open .app-select-trigger {
  outline: none;
  border-color: var(--primary, #1f6feb);
  box-shadow: 0 0 0 3px rgba(31, 111, 235, 0.16);
}

.app-select.is-invalid .app-select-trigger {
  border-color: var(--danger, #b42318);
  box-shadow: 0 0 0 3px rgba(180, 35, 24, 0.12);
}

.app-select-trigger:disabled {
  background: var(--disabled-bg, #f1f5f9);
  color: var(--disabled-text, #64748b);
  cursor: not-allowed;
}

.app-select-chevron {
  position: absolute;
  top: 50%;
  right: 14px;
  width: 8px;
  height: 8px;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: translateY(-70%) rotate(45deg);
  transition: transform 160ms ease;
  pointer-events: none;
}

.app-select.is-open .app-select-chevron {
  transform: translateY(-25%) rotate(225deg);
}

.app-select-native {
  position: absolute;
  left: 1px;
  bottom: 1px;
  width: 1px;
  height: 1px;
  margin: 0;
  padding: 0;
  border: 0;
  opacity: 0;
  pointer-events: none;
}

.app-select-menu {
  position: fixed;
  z-index: 10020;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid #c9d5e3;
  border-radius: 7px;
  background: #fff;
  box-shadow: 0 18px 42px rgba(15, 23, 42, 0.18);
  transform-origin: top center;
}

.app-select-menu.has-descriptions {
  grid-template-columns: minmax(0, 1fr) minmax(180px, 0.9fr);
}

.app-select-options {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 5px;
  scrollbar-width: thin;
}

.app-select-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  min-height: 40px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  padding: 8px 10px;
  color: #243148;
  font: inherit;
  line-height: 1.45;
  text-align: left;
  cursor: pointer;
}

.app-select-option:hover,
.app-select-option.is-active {
  background: #eef5ff;
  color: #174f9e;
}

.app-select-option.is-selected {
  color: #1557b0;
  font-weight: 700;
}

.app-select-option i {
  flex: none;
  color: var(--primary, #1f6feb);
  font-style: normal;
}

.app-select-option.is-disabled {
  background: transparent;
  color: #98a2b3;
  cursor: not-allowed;
}

.app-select-description {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
  border-left: 1px solid #e3eaf2;
  background: #f8fafc;
  padding: 13px 14px;
  color: #475467;
}

.app-select-description strong {
  color: #1d2939;
  font-size: 14px;
}

.app-select-description span {
  font-size: 13px;
  line-height: 1.65;
}

.app-select-menu-enter-active,
.app-select-menu-leave-active {
  transition: opacity 140ms ease, transform 140ms ease;
}

.app-select-menu-enter-from,
.app-select-menu-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

@media (max-width: 560px) {
  .app-select-menu.has-descriptions {
    grid-template-columns: minmax(0, 1fr);
  }

  .app-select-description {
    border-top: 1px solid #e3eaf2;
    border-left: 0;
    padding: 10px 12px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .app-select-trigger,
  .app-select-chevron,
  .app-select-menu-enter-active,
  .app-select-menu-leave-active {
    transition: none;
  }
}
</style>
