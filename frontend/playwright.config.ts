import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  // The local ASGI process and shared demo accounts are stateful; serial browser
  // projects keep validation representative and prevent artificial connection bursts.
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['html', { open: 'never' }], ['list']] : 'list',
  outputDir: '../storage/test-results/playwright',
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:8010',
    channel: 'chrome',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off'
  },
  projects: [
    {
      name: 'desktop-1440',
      use: { viewport: { width: 1440, height: 900 } }
    },
    {
      name: 'tablet-768',
      use: { viewport: { width: 768, height: 1024 } }
    },
    {
      name: 'mobile-390',
      use: {
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true
      }
    }
  ]
})
