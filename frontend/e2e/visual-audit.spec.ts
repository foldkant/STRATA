import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { credentials, login, settlePage, type RoleName } from './helpers'

const lessonId = process.env.E2E_LESSON_ID || '3'
const classroomId = process.env.E2E_CLASSROOM_ID || '3'
const courseId = process.env.E2E_COURSE_ID || '3'
const assessmentId = process.env.E2E_ASSESSMENT_ID || '3'

const routes: Record<RoleName, string[]> = {
  superAdmin: [
    '/app/super-admin',
    '/app/super-admin/schools',
    '/app/super-admin/school-admins',
    '/app/super-admin/collection',
    '/app/super-admin/analysis',
    '/app/super-admin/health',
    '/app/super-admin/curriculum-standards'
  ],
  schoolAdmin: [
    '/app/school-admin',
    '/app/school-admin/teachers',
    '/app/school-admin/students',
    '/app/school-admin/classes',
    '/app/school-admin/teaching',
    '/app/school-admin/pretests',
    '/app/school-admin/resource-reviews',
    '/app/school-admin/question-reviews',
    '/app/school-admin/data-quality',
    '/app/school-admin/models'
    // The education-experiment area is intentionally excluded pending redesign.
  ],
  teacher: [
    '/app/teacher',
    '/app/teacher/courses',
    `/app/teacher/lessons/${lessonId}/design`,
    '/app/teacher/classroom',
    `/app/teacher/classroom/${classroomId}`,
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
  ],
  student: [
    '/app/student',
    '/app/student/onboarding',
    '/app/student/courses',
    '/app/student/resources',
    `/app/student/courses/${courseId}`,
    `/app/student/lessons/${lessonId}/workspace`,
    `/app/student/classroom/${classroomId}`,
    '/app/student/assessments',
    `/app/student/assessments/${assessmentId}`,
    '/app/student/profile',
    '/app/student/notices',
    '/app/student/feedback'
  ]
}

for (const [role, roleRoutes] of Object.entries(routes) as Array<[RoleName, string[]]>) {
  test(`${role} page inventory has no unhandled page or server errors`, async ({ page }, testInfo) => {
    test.skip(!credentials(role).available, `Set ${role} E2E credentials to run this audit.`)
    const auditRoot = join(
      '..',
      'docs',
      'platform-audit-2026-07-24',
      'verification-screenshots',
      testInfo.project.name,
      role
    )
    mkdirSync(auditRoot, { recursive: true })
    const findings: Array<{ route: string; kind: string; detail: string }> = []
    let currentRoute = ''
    page.on('pageerror', (error) => {
      const detail = error.stack || error.message
      findings.push({
        route: currentRoute,
        kind: detail.includes('/web-apps/') ? 'external-preview-error' : 'page-error',
        detail
      })
    })
    page.on('response', (response) => {
      if (response.status() >= 500) {
        findings.push({
          route: currentRoute,
          kind: 'server-error',
          detail: `${response.status()} ${response.url()}`
        })
      }
    })

    await login(page, role)
    for (const route of roleRoutes) {
      currentRoute = route
      await page.goto(route)
      await settlePage(page)
      const classroomLoader = page.locator('.classroom-fullscreen-loading')
      if (await classroomLoader.count()) {
        await classroomLoader.waitFor({ state: 'hidden', timeout: 20_000 })
      }
      await expect(page.locator('#app')).toBeVisible()
      const slug = route.replace(/^\/app\/?/, '').replace(/[^a-zA-Z0-9-]+/g, '-') || 'home'
      await page.screenshot({ path: join(auditRoot, `${slug}.png`), fullPage: true })
      const externalPreviewFailed = findings.some(
        (item) => item.route === route && item.kind === 'external-preview-error'
      )
      if (externalPreviewFailed) {
        await expect(
          page.locator('.onlyoffice-fallback:visible'),
          'An external preview failure must leave a visible retry/download path.'
        ).toBeVisible()
      }
    }
    writeFileSync(
      join(auditRoot, 'browser-findings.json'),
      JSON.stringify({ role, viewport: testInfo.project.name, findings }, null, 2),
      'utf8'
    )
    const platformFindings = findings.filter((item) => item.kind !== 'external-preview-error')
    expect(platformFindings, JSON.stringify(findings, null, 2)).toEqual([])
  })
}
