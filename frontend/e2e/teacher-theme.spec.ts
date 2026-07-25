import { expect, test } from '@playwright/test'
import { credentials, login, settlePage } from './helpers'

const lessonId = process.env.E2E_LESSON_ID || '3'
const classroomId = process.env.E2E_CLASSROOM_ID || '3'

const shellRoutes = [
  '/app/teacher',
  '/app/teacher/courses',
  `/app/teacher/lessons/${lessonId}/design`,
  '/app/teacher/classroom',
  '/app/teacher/assessments',
  '/app/teacher/evaluations',
  '/app/teacher/students',
  '/app/teacher/question-bank',
  '/app/teacher/documents',
  '/app/teacher/ai',
  '/app/teacher/resources',
  '/app/teacher/stratification',
  '/app/teacher/notices',
  '/app/teacher/feedback'
]

test('teacher workspace keeps the approved visual system across all shell pages', async ({ page }) => {
  test.skip(!credentials('teacher').available, 'Set teacher E2E credentials to run this review.')
  const pageErrors: string[] = []
  const externalPreviewErrors: string[] = []
  const serverErrors: string[] = []

  page.on('pageerror', (error) => {
    const detail = error.stack || error.message
    if (detail.includes('/web-apps/')) {
      externalPreviewErrors.push(detail)
      return
    }
    pageErrors.push(detail)
  })
  page.on('response', (response) => {
    if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`)
  })

  await login(page, 'teacher')
  for (const route of shellRoutes) {
    const externalPreviewErrorCount = externalPreviewErrors.length
    await page.goto(route)
    await settlePage(page)
    await expect(page.locator('body')).toHaveClass(/teacher-theme-active/)
    await expect(page.locator('.app-shell-teacher')).toBeVisible()

    const presentation = await page.evaluate(() => {
      const shell = document.querySelector<HTMLElement>('.app-shell-teacher')
      const navLink = document.querySelector<HTMLElement>('.app-shell-teacher .nav-group a')
      const title = document.querySelector<HTMLElement>('.app-shell-teacher .topbar h1')
      return {
        font: shell ? getComputedStyle(shell).fontFamily : '',
        primary: shell ? getComputedStyle(shell).getPropertyValue('--teacher-ink').trim() : '',
        navHeight: navLink?.getBoundingClientRect().height || 0,
        titleSize: Number.parseFloat(title ? getComputedStyle(title).fontSize : '0'),
        overflow: document.documentElement.scrollWidth - window.innerWidth
      }
    })

    expect(presentation.font).toContain('STRATA WenKai UI')
    expect(presentation.primary.toLowerCase()).toBe('#17483f')
    expect(presentation.navHeight).toBeGreaterThanOrEqual(42)
    expect(presentation.titleSize).toBeGreaterThanOrEqual(20)
    expect(presentation.overflow).toBeLessThanOrEqual(1)

    if (route === '/app/teacher/evaluations') {
      const guideCopy = page.locator('.evaluation-guide > header > div:first-child')
      await expect(guideCopy).toBeVisible()
      const box = await guideCopy.boundingBox()
      expect(box?.width || 0).toBeGreaterThanOrEqual(250)
      expect(box?.height || Number.POSITIVE_INFINITY).toBeLessThan(480)
    }

    if (externalPreviewErrors.length > externalPreviewErrorCount) {
      await expect(page.locator('.onlyoffice-fallback:visible, .onlyoffice-loading-recovery:visible')).toBeVisible()
    }
  }

  expect(pageErrors).toEqual([])
  expect(serverErrors).toEqual([])
})

test('teacher classroom console inherits the teacher theme without the application shell', async ({ page }) => {
  test.skip(!credentials('teacher').available, 'Set teacher E2E credentials to run this review.')
  await login(page, 'teacher')
  await page.goto(`/app/teacher/classroom/${classroomId}`)
  await settlePage(page)
  await page.locator('.classroom-fullscreen-loading').waitFor({ state: 'hidden', timeout: 20_000 })

  await expect(page.locator('body')).toHaveClass(/teacher-theme-active/)
  await expect(page.locator('.teacher-classroom-fullscreen')).toBeVisible()
  await expect(page.locator('.app-shell')).toHaveCount(0)

  const presentation = await page.evaluate(() => {
    const consolePage = document.querySelector<HTMLElement>('.teacher-classroom-fullscreen')
    return {
      font: consolePage ? getComputedStyle(consolePage).fontFamily : '',
      accent: consolePage ? getComputedStyle(consolePage).getPropertyValue('--classroom-accent').trim() : '',
      overflow: document.documentElement.scrollWidth - window.innerWidth
    }
  })

  expect(presentation.font).toContain('STRATA WenKai UI')
  expect(['var(--teacher-ink)', '#17483f']).toContain(presentation.accent.toLowerCase())
  expect(presentation.overflow).toBeLessThanOrEqual(1)
})
