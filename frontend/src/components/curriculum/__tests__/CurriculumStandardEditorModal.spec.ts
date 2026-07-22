import { afterEach, describe, expect, it } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, nextTick, ref } from 'vue'
import CurriculumStandardEditorModal from '../CurriculumStandardEditorModal.vue'

let wrapper: VueWrapper | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('curriculum modal keyboard access', () => {
  it('focuses the dialog, constrains Tab, closes on Escape, and restores the trigger', async () => {
    const Host = defineComponent({
      components: { CurriculumStandardEditorModal },
      setup() {
        const open = ref(false)
        return { open }
      },
      template: `
        <button id="open-standard" type="button" @click="open = true">登记课程标准</button>
        <CurriculumStandardEditorModal v-if="open" :draft="null" @close="open = false" />
      `
    })

    wrapper = mount(Host, {
      attachTo: document.body,
      global: {
        stubs: {
          AppSelect: {
            template: '<select><slot /></select>'
          }
        }
      }
    })

    const trigger = wrapper.get<HTMLButtonElement>('#open-standard')
    trigger.element.focus()
    await trigger.trigger('click')
    await nextTick()

    const dialog = wrapper.get<HTMLElement>('[role="dialog"]')
    const initial = dialog.get<HTMLButtonElement>('[data-modal-initial-focus]')
    const focusableButtons = dialog.findAll<HTMLButtonElement>('button:not([disabled])')
    const last = focusableButtons[focusableButtons.length - 1]

    expect(document.activeElement).toBe(initial.element)

    last.element.focus()
    await last.trigger('keydown', { key: 'Tab' })
    expect(document.activeElement).toBe(initial.element)

    await initial.trigger('keydown', { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(last.element)

    await last.trigger('keydown', { key: 'Escape' })
    await nextTick()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
  })
})
