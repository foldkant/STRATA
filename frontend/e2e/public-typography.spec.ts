import { expect, test } from '@playwright/test'

const publicPages = [
  { name: 'home', path: '/' },
  { name: 'login', path: '/login/' }
] as const

for (const publicPage of publicPages) {
  test(`${publicPage.name} uses the local public typography without horizontal overflow`, async ({
    page
  }, testInfo) => {
    const externalRequests: string[] = []

    page.on('request', (request) => {
      const url = new URL(request.url())
      if (url.protocol.startsWith('http') && url.hostname !== '127.0.0.1' && url.hostname !== 'localhost') {
        externalRequests.push(request.url())
      }
    })

    await page.goto(publicPage.path, { waitUntil: 'networkidle' })
    await page.evaluate(() => document.fonts.ready)
    await page.waitForTimeout(2100)

    const emblem = page.locator('.brand-emblem')
    await expect(emblem).toHaveCount(1)

    const visibleLogo = page.locator('img[src*="/static/brand/brand-logo.png"]:visible').first()
    await expect(visibleLogo).toBeVisible()
    expect(await visibleLogo.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0)

    const typography = await page.evaluate(() => ({
      bodyFamily: getComputedStyle(document.body).fontFamily,
      fontReady: document.fonts.check('16px "STRATA WenKai"'),
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth
    }))

    expect(typography.bodyFamily).toContain('STRATA WenKai')
    expect(typography.fontReady).toBe(true)
    expect(typography.documentWidth).toBeLessThanOrEqual(typography.viewportWidth + 1)
    expect(externalRequests).toEqual([])

    await page.screenshot({
      path: testInfo.outputPath(`${publicPage.name}.png`),
      fullPage: true
    })
  })
}
