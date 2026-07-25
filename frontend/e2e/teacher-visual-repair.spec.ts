import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { credentials, login, settlePage } from './helpers'

const classroomId = process.env.E2E_CLASSROOM_ID || '310'

function screenshotPath(projectName: string, name: string) {
  const directory = join(
    '..',
    'docs',
    'platform-audit-2026-07-24',
    'teacher-visual-repair',
    projectName
  )
  mkdirSync(directory, { recursive: true })
  return join(directory, name)
}

test('teacher course editor uses the teacher palette for its default cover', async ({ page }, testInfo) => {
  test.skip(!credentials('teacher').available, 'Set teacher E2E credentials to run this review.')
  await login(page, 'teacher')
  await page.goto('/app/teacher/courses')
  await settlePage(page)

  await page.getByRole('button', { name: '新增课程' }).click()
  const dialog = page.getByRole('dialog')
  const cover = dialog.locator('.course-cover-default.large')
  await expect(cover).toBeVisible()

  const coverPaint = await cover.evaluate((element) => {
    const style = getComputedStyle(element)
    return `${style.backgroundColor} ${style.backgroundImage}`
  })
  expect(coverPaint).not.toContain('31, 111, 235')
  expect(coverPaint).toContain('23, 72, 63')

  await page.screenshot({
    path: screenshotPath(testInfo.project.name, 'teacher-course-editor.png'),
    fullPage: true
  })
})

test('classroom evaluation is a usable teacher workspace without legacy blue paint', async ({ page }, testInfo) => {
  test.skip(!credentials('teacher').available, 'Set teacher E2E credentials to run this review.')
  await login(page, 'teacher')
  await page.goto(`/app/teacher/classroom/${classroomId}`)
  await page.locator('.classroom-fullscreen-loading').waitFor({ state: 'hidden', timeout: 20_000 })

  const entry = page.getByRole('button', { name: /评价情况/ })
  await expect(entry).toBeEnabled()
  await entry.click()

  const modal = page.locator('.runtime-evaluation-modal')
  const body = modal.locator('.runtime-evaluation-body')
  await expect(modal).toBeVisible()
  await expect(page.getByRole('heading', { name: '课堂评价情况' })).toBeVisible()

  const measurements = await modal.evaluate((element) => {
    const box = element.getBoundingClientRect()
    const bodyElement = element.querySelector<HTMLElement>('.runtime-evaluation-body')
    return {
      width: box.width,
      right: box.right,
      bottom: box.bottom,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      bodyOverflow: bodyElement ? bodyElement.scrollWidth - bodyElement.clientWidth : 0
    }
  })
  expect(measurements.right).toBeLessThanOrEqual(measurements.viewportWidth + 1)
  expect(measurements.bottom).toBeLessThanOrEqual(measurements.viewportHeight + 1)
  expect(measurements.bodyOverflow).toBeLessThanOrEqual(2)

  const panels = await body.locator(':scope > section').evaluateAll((elements) => (
    elements.map((element) => {
      const box = element.getBoundingClientRect()
      return { top: box.top, bottom: box.bottom }
    })
  ))
  if (panels.length > 1 && panels[1].top > panels[0].top) {
    expect(panels[0].bottom).toBeLessThanOrEqual(panels[1].top + 1)
  }

  const setup = modal.locator('.teacher-evaluation-setup')
  const workspace = modal.locator('.teacher-evaluation-layout')
  if (await setup.isVisible()) {
    await expect(setup.getByText('需要先完成课时设计')).toBeVisible()
    await expect(modal.locator('.teacher-evaluation-student-list')).toHaveCount(0)
  } else {
    await expect(workspace).toBeVisible()
    await expect(workspace.getByLabel('查找学生')).toBeVisible()
    const formOverflow = await workspace.locator('.teacher-evaluation-form').evaluate(
      (element) => element.scrollWidth - element.clientWidth
    )
    expect(formOverflow).toBeLessThanOrEqual(2)
  }

  const legacyBluePaint = await modal.locator('*').evaluateAll((elements) => {
    const legacyBlue = /(rgb\(31,\s*111,\s*235\)|rgb\(29,\s*78,\s*216\)|rgb\(30,\s*64,\s*175\))/
    return elements
      .filter((element) => {
        const box = element.getBoundingClientRect()
        return box.width > 0 && box.height > 0
      })
      .map((element) => {
        const style = getComputedStyle(element)
        return `${style.color} ${style.backgroundColor} ${style.borderColor}`
      })
      .filter((paint) => legacyBlue.test(paint))
  })
  expect(legacyBluePaint).toEqual([])

  await expect(body).toBeVisible()
  await page.screenshot({
    path: screenshotPath(testInfo.project.name, 'classroom-evaluation.png'),
    fullPage: true
  })
})
