import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { credentials, login, settlePage, type RoleName } from './helpers'

const homePaths: Array<[RoleName, string]> = [
  ['superAdmin', '/app/super-admin'],
  ['schoolAdmin', '/app/school-admin'],
  ['teacher', '/app/teacher'],
  ['student', '/app/student']
]

for (const [role, homePath] of homePaths) {
  test(`${role} can sign in and reach the correct work area`, async ({ page }) => {
    test.skip(!credentials(role).available, `Set ${role} E2E credentials to run this check.`)
    const serverErrors: string[] = []
    page.on('response', (response) => {
      if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`)
    })
    await login(page, role)
    await page.goto(homePath)
    await settlePage(page)
    await expect(page.locator('#app')).toBeVisible()
    expect(serverErrors).toEqual([])
  })
}

test('teacher lesson evaluation stays in one workspace and both authoring paths open', async ({ page }) => {
  test.skip(!credentials('teacher').available, 'Set teacher E2E credentials to run this check.')
  const lessonId = process.env.E2E_AUTHORING_LESSON_ID || process.env.E2E_LESSON_ID || '3'
  await login(page, 'teacher')
  await page.goto(`/app/teacher/lessons/${lessonId}/design`)
  await settlePage(page)

  const entry = page.getByRole('button', { name: /新建或选择评价|查看或调整评价安排|环节评价/ }).first()
  await expect(entry).toBeVisible()
  await entry.click()
  await expect(page.getByRole('heading', { name: '为当前环节安排评价' })).toBeVisible()
  await expect(page.locator('.step-evaluation-modal')).toHaveAttribute('role', 'region')
  await expect(page.locator('[role="dialog"]')).toHaveCount(0)

  const manual = page.locator('[data-test="lesson-manual-draft"]:visible').first()
  await expect(manual).toBeEnabled()
  await manual.click()
  const manualDialog = page.getByRole('dialog')
  await expect(manualDialog).toHaveCount(1)
  await expect(page.getByRole('heading', { name: /新建评价方案|编辑评价方案/ })).toBeVisible()
  await manualDialog.getByRole('button', { name: /关闭|取消/ }).first().click()

  const ai = page.locator('[data-test="lesson-ai-draft"]:visible').first()
  await expect(ai).toBeEnabled()
  await ai.click()
  await expect(page.getByRole('dialog')).toHaveCount(1)
  await expect(page.locator('.ai-draft-wizard').getByText(/本次课程内容/).first()).toBeVisible()
})

test('teacher active classroom reaches a usable control console', async ({ page }) => {
  test.skip(!credentials('teacher').available, 'Set teacher E2E credentials to run this check.')
  const classroomId = process.env.E2E_CLASSROOM_ID || '3'
  await login(page, 'teacher')
  await page.goto(`/app/teacher/classroom/${classroomId}`)
  await page.locator('.classroom-fullscreen-loading').waitFor({ state: 'hidden', timeout: 20_000 })
  await expect(page.locator('.classroom-console-shell')).toBeVisible()
  const evaluationButton = page.getByRole('button', { name: /评价情况/ })
  await expect(evaluationButton).toBeEnabled()
  await evaluationButton.click()
  await expect(page.getByRole('heading', { name: '课堂评价情况' })).toBeVisible()
  await expect(page.getByText(/评价内容来自课时设计/)).toBeVisible()
})

test('teacher can expand a long class list and open an assigned student learning profile', async ({ page }, testInfo) => {
  test.skip(!credentials('teacher').available, 'Set teacher E2E credentials to run this check.')
  await login(page, 'teacher')
  await page.goto('/app/teacher/students')
  await settlePage(page)

  const classScope = page.locator('section.teacher-class-strip')
  await expect(classScope).toBeVisible()
  await expect(classScope.getByRole('heading', { name: '任教班级' })).toBeVisible()
  await expect(classScope.getByRole('button', { name: '全部班级' })).toBeVisible()
  const collapsedClassCount = await classScope.locator('.class-filter-chip').count()
  const expandClasses = classScope.getByRole('button', { name: /展开更多班级/ })
  await expect(expandClasses).toHaveAttribute('aria-expanded', 'false')
  await expandClasses.click()
  await expect(classScope.getByRole('button', { name: '收起更多班级' })).toHaveAttribute('aria-expanded', 'true')
  expect(await classScope.locator('.class-filter-chip').count()).toBeGreaterThan(collapsedClassCount)
  await classScope.getByRole('button', { name: '收起更多班级' }).click()
  await expect(expandClasses).toHaveAttribute('aria-expanded', 'false')
  await expect(classScope).toBeVisible()
  await page.locator('#app-main-content').evaluate((element) => {
    element.scrollTop = 0
  })

  const screenshotDir = join(
    '..',
    'docs',
    'platform-audit-2026-07-24',
    'verification-screenshots',
    testInfo.project.name,
    'teacher'
  )
  mkdirSync(screenshotDir, { recursive: true })
  await page.screenshot({
    path: join(screenshotDir, 'students-learning-situation.png'),
    fullPage: true
  })

  const profileLink = page.getByRole('link', { name: '查看学习档案' }).first()
  await expect(profileLink).toBeVisible()
  await profileLink.click()
  await page.waitForURL(/\/app\/teacher\/students\/\d+\/profile$/)
  await settlePage(page)

  await expect(page.getByRole('heading', { name: '学生学习档案', level: 1 })).toBeVisible()
  await expect(page.getByText('仅显示本人任教学科课程相关记录')).toBeVisible()
  await expect(page.getByRole('button', { name: '课程学习' })).toBeVisible()
  await expect(page.getByRole('button', { name: '测试与作品' })).toBeVisible()
  await expect(page.getByRole('button', { name: '评价与轨迹' })).toBeVisible()

  await page.screenshot({
    path: join(screenshotDir, 'student-learning-profile.png'),
    fullPage: true
  })
})

test('teacher can review all pending stratification suggestions in the current scope', async ({ page }, testInfo) => {
  test.skip(!credentials('teacher').available, 'Set teacher E2E credentials to run this check.')
  await login(page, 'teacher')
  await page.goto('/app/teacher/stratification?view=pending')
  await settlePage(page)

  const courseSelect = page.locator('.stratification-scope-bar .app-select').nth(1)
  await courseSelect.getByRole('combobox').click()
  await page.getByRole('option', { name: '数据与计算', exact: true }).click()
  const reviewAll = page.locator('[data-test="stratification-review-all"]')
  await expect(reviewAll).toBeVisible()
  await expect(reviewAll).toBeEnabled()
  await reviewAll.click()
  const dialog = page.getByRole('dialog', { name: '批量处理全部建议' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText(/不受表格分页影响/)).toBeVisible()
  await expect(dialog.getByRole('button', { name: /确认处理全部/ })).toBeVisible()
  const screenshotDir = join(
    '..',
    'docs',
    'platform-audit-2026-07-24',
    'verification-screenshots',
    testInfo.project.name,
    'teacher'
  )
  mkdirSync(screenshotDir, { recursive: true })
  await page.screenshot({
    path: join(screenshotDir, 'stratification-review-all.png'),
    fullPage: true
  })
  await dialog.getByRole('button', { name: '取消' }).click()
  await expect(dialog).toBeHidden()
})

test('teacher lesson evaluation boundaries keep their card layout', async ({ page }, testInfo) => {
  test.skip(!credentials('teacher').available, 'Set teacher E2E credentials to run this check.')
  await login(page, 'teacher')
  await page.goto('/app/teacher/lessons/86/design')
  await settlePage(page)

  await page.locator('.designer-tabs').getByRole('button', { name: '评价', exact: true }).click()
  const useMap = page.locator('[data-test="lesson-evaluation-use-map"]')
  await expect(useMap).toBeVisible()
  await expect(useMap.locator('article')).toHaveCount(3)
  const presentation = await useMap.evaluate((element) => {
    const sectionStyle = window.getComputedStyle(element)
    const cardStyle = window.getComputedStyle(element.querySelector('article')!)
    return {
      display: sectionStyle.display,
      backgroundImage: sectionStyle.backgroundImage,
      border: sectionStyle.borderStyle,
      cardBorder: cardStyle.borderStyle,
      cardBackground: cardStyle.backgroundColor
    }
  })
  expect(presentation.display).toBe('grid')
  expect(presentation.backgroundImage).not.toBe('none')
  expect(presentation.border).toBe('solid')
  expect(presentation.cardBorder).toBe('solid')
  expect(presentation.cardBackground).not.toBe('rgba(0, 0, 0, 0)')

  const screenshotDir = join(
    '..',
    'docs',
    'platform-audit-2026-07-24',
    'verification-screenshots',
    testInfo.project.name,
    'teacher'
  )
  mkdirSync(screenshotDir, { recursive: true })
  await useMap.screenshot({
    path: join(screenshotDir, 'lesson-evaluation-boundaries.png')
  })
})

test('student can open a classroom-deployed resource without an authorization failure', async ({ page }) => {
  test.skip(!credentials('student').available, 'Set student E2E credentials to run this check.')
  const classroomId = process.env.E2E_CLASSROOM_ID || '3'
  const authorizationFailures: string[] = []
  page.on('response', (response) => {
    if (
      response.url().includes('/api/v1/resources/')
      && [401, 403].includes(response.status())
    ) {
      authorizationFailures.push(`${response.status()} ${response.url()}`)
    }
  })
  await login(page, 'student')
  await page.goto(`/app/student/classroom/${classroomId}`)
  await settlePage(page)
  await expect(page.locator('.student-classroom-resource-pane')).toBeVisible()
  await expect(page.getByText(/演示文稿1/).first()).toBeVisible()
  await expect(
    page.locator(
      '.student-classroom-resource-pane iframe:visible, '
      + '.student-classroom-resource-pane .onlyoffice-loading-recovery:visible, '
      + '.student-classroom-resource-pane .onlyoffice-fallback:visible'
    ).first()
  ).toBeVisible()
  expect(authorizationFailures).toEqual([])
})

test('AI question generation explains that the task continues in background', async ({ page }) => {
  test.skip(!credentials('teacher').available, 'Set teacher E2E credentials to run this check.')
  await login(page, 'teacher')
  await page.goto('/app/teacher/question-bank')
  await settlePage(page)
  await page.getByRole('button', { name: 'AI 批量出题' }).click()
  await expect(page.getByRole('heading', { name: 'AI 批量出题' })).toBeVisible()
  await expect(page.getByText(/可以关闭窗口或离开本页/).first()).toBeAttached()
  await expect(page.getByRole('button', { name: /生成题目草稿/ })).toBeEnabled()
})
