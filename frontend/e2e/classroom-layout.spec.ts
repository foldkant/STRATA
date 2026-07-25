import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { credentials, login } from './helpers'

test('teacher classroom console keeps the teaching surface and controls in reach', async ({ page }, testInfo) => {
  test.skip(!credentials('teacher').available, 'Set teacher E2E credentials to run this check.')
  const classroomId = process.env.E2E_CLASSROOM_LAYOUT_ID || process.env.E2E_CLASSROOM_ID || '3'
  await login(page, 'teacher')
  await page.goto(`/app/teacher/classroom/${classroomId}`)
  await page.locator('.classroom-fullscreen-loading').waitFor({ state: 'hidden', timeout: 20_000 })

  const shell = page.locator('.classroom-console-shell')
  await expect(shell).toBeVisible()
  const contextTabs = page.locator('.classroom-context-tabs')
  await expect(contextTabs.getByRole('tab')).toHaveCount(3)
  await expect(page.locator('#classroom-tab-task')).toHaveAttribute('aria-selected', 'true')

  const resourceTabs = page.locator('.teacher-classroom-fullscreen .classroom-resource-tabs')
  if (await resourceTabs.count()) {
    await expect(resourceTabs).toBeVisible()
    expect((await resourceTabs.boundingBox())!.height).toBeLessThanOrEqual(52)
    expect(await resourceTabs.getByRole('tab').count()).toBeGreaterThan(1)
    const secondResource = resourceTabs.getByRole('tab').nth(1)
    await secondResource.click()
    await expect(secondResource).toHaveAttribute('aria-selected', 'true')
    await resourceTabs.getByRole('tab').first().click()
  }

  const viewport = page.viewportSize()!
  const controlBoxes = await page.locator('.compact-classroom-controls button').evaluateAll((buttons) => (
    buttons.map((button) => {
      const box = button.getBoundingClientRect()
      return { left: box.left, right: box.right, width: box.width, height: box.height }
    })
  ))
  expect(controlBoxes).toHaveLength(4)
  for (const box of controlBoxes) {
    expect(box.left).toBeGreaterThanOrEqual(0)
    expect(box.right).toBeLessThanOrEqual(viewport.width)
    expect(box.width).toBeGreaterThan(0)
  }

  const pageSize = await page.evaluate(() => ({
    width: document.documentElement.scrollWidth,
    height: document.documentElement.scrollHeight
  }))
  expect(pageSize.width).toBeLessThanOrEqual(viewport.width)
  if (testInfo.project.name === 'desktop-1440') {
    expect(pageSize.height).toBeLessThanOrEqual(viewport.height + 2)
  } else {
    const resourceStage = await page.locator('.classroom-resource-stage').boundingBox()
    expect(resourceStage).not.toBeNull()
    expect(resourceStage!.y).toBeLessThan(viewport.height)
  }

  const screenshotDir = join(
    '..',
    'docs',
    'platform-audit-2026-07-24',
    'classroom-309-redesign',
    'verified',
    testInfo.project.name
  )
  mkdirSync(screenshotDir, { recursive: true })
  await page.screenshot({ path: join(screenshotDir, 'teacher-classroom-overview.png'), fullPage: true })

  await page.locator('#classroom-tab-status').click()
  await expect(page.locator('#classroom-panel-status')).toBeVisible()
  await expect(page.locator('#classroom-tab-status')).toHaveAttribute('aria-selected', 'true')
  await page.locator('#classroom-tab-task').click()
  const firstQuestion = page.locator('.classroom-question-item').first()
  if (await firstQuestion.count()) {
    await firstQuestion.locator('summary').click()
    await expect(firstQuestion).toHaveAttribute('open', '')
  }

  if (testInfo.project.name === 'desktop-1440') {
    await shell.evaluate((element) => {
      element.classList.add('has-active-timer')
      const banner = document.createElement('section')
      banner.className = 'teacher-timer-banner'
      banner.dataset.test = 'simulated-timer'
      banner.textContent = '课堂倒计时 05:00'
      element.querySelector('.classroom-control-grid')?.before(banner)
    })
    const gridWithTimer = await page.locator('.classroom-control-grid').boundingBox()
    expect(gridWithTimer).not.toBeNull()
    expect(gridWithTimer!.y + gridWithTimer!.height).toBeLessThanOrEqual(viewport.height)
    await shell.evaluate((element) => {
      element.classList.remove('has-active-timer')
      element.querySelector('[data-test="simulated-timer"]')?.remove()
    })
  }

  await page.screenshot({ path: join(screenshotDir, 'teacher-classroom-expanded.png'), fullPage: true })
})
