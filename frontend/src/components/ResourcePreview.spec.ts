import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ResourcePreview from './ResourcePreview.vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({
    resolve: (path: string) => ({ href: path })
  })
}))

describe('ResourcePreview', () => {
  it('offers a page-level expand control and reports both expand states', async () => {
    const wrapper = mount(ResourcePreview, {
      props: {
        resource: {
          id: 3,
          title: '导入视频',
          attachment_name: '小榄中学宣传片2024五分钟版.mp4',
          attachment_url: '/api/v1/files/resources/3/attachment/',
          file_ext: 'mp4'
        },
        expandable: true,
        expanded: false
      }
    })

    const expandButton = wrapper.get('[data-test="resource-preview-expand"]')
    expect(expandButton.text()).toContain('放大查看')
    expect(expandButton.attributes('aria-pressed')).toBe('false')

    await expandButton.trigger('click')
    expect(wrapper.emitted('toggle-expand')).toHaveLength(1)

    await wrapper.setProps({ expanded: true })
    expect(wrapper.get('[data-test="resource-preview-expand"]').text()).toContain('返回课堂')
    expect(wrapper.get('[data-test="resource-preview-expand"]').attributes('aria-pressed')).toBe('true')
  })

  it('does not show the expand control when no resource is selected', () => {
    const wrapper = mount(ResourcePreview, {
      props: {
        resource: null,
        expandable: true
      }
    })

    expect(wrapper.find('[data-test="resource-preview-expand"]').exists()).toBe(false)
  })
})
