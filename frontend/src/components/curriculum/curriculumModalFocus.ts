import { nextTick, type Directive } from 'vue'

type CloseHandler = () => void

type ModalFocusState = {
  close: CloseHandler
  opener: HTMLElement | null
  onKeydown: (event: KeyboardEvent) => void
}

const modalStates = new WeakMap<HTMLElement, ModalFocusState>()
const focusableSelector = [
  'a[href]',
  'area[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])'
].join(',')

function focusableElements(dialog: HTMLElement) {
  return Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector)).filter((element) => (
    !element.hidden
    && element.getAttribute('aria-hidden') !== 'true'
    && !element.closest('[inert]')
  ))
}

function focusInitialElement(dialog: HTMLElement) {
  const preferred = dialog.querySelector<HTMLElement>('[data-modal-initial-focus]')
  const target = preferred || focusableElements(dialog)[0] || dialog
  target.focus({ preventScroll: true })
}

export const vCurriculumModalFocus: Directive<HTMLElement, CloseHandler> = {
  mounted(dialog, binding) {
    if (!dialog.hasAttribute('tabindex')) dialog.tabIndex = -1

    const state: ModalFocusState = {
      close: binding.value,
      opener: document.activeElement instanceof HTMLElement ? document.activeElement : null,
      onKeydown: () => undefined
    }

    state.onKeydown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing) return
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        state.close()
        return
      }
      if (event.key !== 'Tab') return

      const elements = focusableElements(dialog)
      if (!elements.length) {
        event.preventDefault()
        event.stopPropagation()
        dialog.focus({ preventScroll: true })
        return
      }

      const first = elements[0]
      const last = elements[elements.length - 1]
      const active = document.activeElement
      if (event.shiftKey && (active === first || !dialog.contains(active))) {
        event.preventDefault()
        event.stopPropagation()
        last.focus({ preventScroll: true })
      } else if (!event.shiftKey && (active === last || !dialog.contains(active))) {
        event.preventDefault()
        event.stopPropagation()
        first.focus({ preventScroll: true })
      }
    }

    modalStates.set(dialog, state)
    dialog.addEventListener('keydown', state.onKeydown)
    void nextTick(() => focusInitialElement(dialog))
  },
  updated(dialog, binding) {
    const state = modalStates.get(dialog)
    if (state) state.close = binding.value
  },
  beforeUnmount(dialog) {
    const state = modalStates.get(dialog)
    if (state) dialog.removeEventListener('keydown', state.onKeydown)
  },
  unmounted(dialog) {
    const state = modalStates.get(dialog)
    modalStates.delete(dialog)
    if (state?.opener?.isConnected) state.opener.focus({ preventScroll: true })
  }
}
