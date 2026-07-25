import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import OnlyOfficeEditor from './OnlyOfficeEditor.vue'

const apiMocks = vi.hoisted(() => ({
  getGroupOfficeConfig: vi.fn(),
  getResourceOfficeConfig: vi.fn()
}))

vi.mock('@/api/office', () => ({
  ...apiMocks
}))

describe('OnlyOfficeEditor', () => {
  beforeEach(() => {
    apiMocks.getResourceOfficeConfig.mockImplementation(
      () => new Promise(() => undefined)
    )
  })

  afterEach(() => {
    vi.useRealTimers()
    document.querySelectorAll('script[data-onlyoffice-api]').forEach((script) => script.remove())
    delete window.DocsAPI
    vi.clearAllMocks()
  })

  it('keeps the original file available while the preview service is loading', () => {
    const wrapper = mount(OnlyOfficeEditor, {
      props: {
        resourceId: 12,
        mode: 'view',
        fallbackUrl: '/api/v1/resources/12/download/',
        fallbackTitle: '下载课堂材料'
      },
      global: {
        stubs: {
          NoticeLine: true
        }
      }
    })

    expect(wrapper.text()).toContain('预览正在加载，您也可以先下载原文件')
    const link = wrapper.get('.onlyoffice-loading-recovery a')
    expect(link.attributes('href')).toBe('/api/v1/resources/12/download/')
    expect(link.text()).toBe('下载课堂材料')
    wrapper.unmount()
  })

  it('offers retry and download when the external editor never becomes ready', async () => {
    vi.useFakeTimers()
    const serverUrl = 'http://office.test'
    const script = document.createElement('script')
    script.dataset.onlyofficeApi = `${serverUrl}/web-apps/apps/api/documents/api.js`
    document.head.appendChild(script)
    window.DocsAPI = {
      DocEditor: class {
        constructor(_elementId: string, _config: Record<string, unknown>) {}
        destroyEditor() {}
      }
    }
    apiMocks.getResourceOfficeConfig.mockResolvedValue({
      server_url: serverUrl,
      config: {
        document: {
          url: '/api/v1/files/resources/12/attachment/',
          title: '课堂材料.pptx'
        }
      }
    })
    const wrapper = mount(OnlyOfficeEditor, {
      props: { resourceId: 12, mode: 'view' },
      global: {
        stubs: {
          NoticeLine: true
        }
      }
    })
    await flushPromises()

    vi.advanceTimersByTime(8_001)
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('文档预览暂不可用')
    expect(wrapper.text()).toContain('重新加载')
    expect(wrapper.get('.onlyoffice-fallback a').attributes('href')).toBe(
      '/api/v1/files/resources/12/attachment/'
    )
    wrapper.unmount()
  })

  it('turns an external editor runtime failure into a retry and download state', async () => {
    const serverUrl = 'http://office.test'
    const script = document.createElement('script')
    script.dataset.onlyofficeApi = `${serverUrl}/web-apps/apps/api/documents/api.js`
    document.head.appendChild(script)
    window.DocsAPI = {
      DocEditor: class {
        constructor(_elementId: string, _config: Record<string, unknown>) {}
        destroyEditor() {}
      }
    }
    apiMocks.getResourceOfficeConfig.mockResolvedValue({
      server_url: serverUrl,
      config: {
        document: {
          url: '/api/v1/files/resources/12/attachment/',
          title: '课堂材料.pptx'
        }
      }
    })
    const wrapper = mount(OnlyOfficeEditor, {
      props: { resourceId: 12, mode: 'view' },
      global: {
        stubs: {
          NoticeLine: true
        }
      }
    })
    await flushPromises()

    window.dispatchEvent(new ErrorEvent('error', {
      filename: `${serverUrl}/web-apps/apps/common/main/lib/component/ColorPaletteExt.js`,
      message: 'Cannot read properties of undefined',
      error: new Error('Cannot read properties of undefined')
    }))
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('文档预览暂不可用')
    expect(wrapper.text()).toContain('重新加载')
    expect(wrapper.get('.onlyoffice-fallback a').attributes('href')).toBe(
      '/api/v1/files/resources/12/attachment/'
    )
    wrapper.unmount()
  })
})
