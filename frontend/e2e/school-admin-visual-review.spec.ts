import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { credentials, login, settlePage } from './helpers'

const routes = [
  { slug: 'dashboard', path: '/app/school-admin' },
  { slug: 'classes', path: '/app/school-admin/classes' },
  { slug: 'teachers', path: '/app/school-admin/teachers' },
  { slug: 'students', path: '/app/school-admin/students' },
  { slug: 'teaching', path: '/app/school-admin/teaching' },
  { slug: 'pretests', path: '/app/school-admin/pretests' },
  { slug: 'resource-reviews', path: '/app/school-admin/resource-reviews' },
  { slug: 'question-reviews', path: '/app/school-admin/question-reviews' },
  { slug: 'data-quality', path: '/app/school-admin/data-quality' },
  { slug: 'learning-support', path: '/app/school-admin/models' }
]

test('school administrator pages share the approved visual language and remain operable', async ({ page }, testInfo) => {
  test.skip(!credentials('schoolAdmin').available, 'Set school administrator E2E credentials.')

  const auditRoot = join(
    '..',
    'docs',
    'ui-self-check',
    'school-admin-review-2026-07-24',
    testInfo.project.name
  )
  mkdirSync(auditRoot, { recursive: true })

  const pageErrors: string[] = []
  const serverErrors: string[] = []
  const externalRequests = new Set<string>()
  const layoutFindings: Array<{ route: string; horizontalOverflow: number }> = []
  page.on('pageerror', (error) => pageErrors.push(error.stack || error.message))
  page.on('response', (response) => {
    if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`)
  })
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) externalRequests.add(url.origin)
  })

  await login(page, 'schoolAdmin')
  for (const route of routes) {
    await page.goto(route.path)
    await settlePage(page)
    await expect(page.locator('.app-shell-school-admin')).toBeVisible()
    await expect(page.locator('.topbar h1')).not.toHaveText('')

    const horizontalOverflow = await page.evaluate(
      () => Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth)
    )
    if (horizontalOverflow > 1) {
      layoutFindings.push({ route: route.path, horizontalOverflow })
    }

    await page.screenshot({
      path: join(auditRoot, `${route.slug}.png`),
      fullPage: true
    })
  }

  await page.goto('/app/school-admin')
  await settlePage(page)
  await expect(page.locator('.school-priority')).toBeVisible()
  await expect(page.locator('.school-shortcuts')).toBeVisible()
  const sidebarColor = await page.locator('.sidebar').evaluate(
    (element) => getComputedStyle(element).backgroundColor
  )
  expect(sidebarColor).toBe('rgb(24, 61, 55)')

  if (testInfo.project.name === 'desktop-1440') {
    await page.goto('/app/school-admin/pretests')
    await settlePage(page)
    const activeTab = page.locator('.pretest-section-tabs button.active')
    await expect(activeTab).toBeVisible()
    const activeTabStyle = await activeTab.evaluate((element) => ({
      color: getComputedStyle(element).color,
      backgroundColor: getComputedStyle(element).backgroundColor
    }))
    expect(activeTabStyle.color).not.toBe('rgb(37, 99, 235)')
    expect(activeTabStyle.backgroundColor).not.toBe('rgb(239, 246, 255)')

    await page.goto('/app/school-admin/resource-reviews')
    await settlePage(page)
    const activeResourceTab = page.locator('.resource-review-tabs button.active')
    await expect(activeResourceTab).toBeVisible()
    const resourceTabStyle = await activeResourceTab.evaluate((element) => ({
      color: getComputedStyle(element).color,
      backgroundColor: getComputedStyle(element).backgroundColor
    }))
    expect(resourceTabStyle.color).toBe('rgb(255, 255, 255)')
    expect(resourceTabStyle.backgroundColor).toBe('rgb(24, 61, 55)')

    await page.goto('/app/school-admin/students')
    await settlePage(page)
    await page.getByRole('button', { name: '新增学生' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    const modalPrimaryStyle = await page.getByRole('dialog').getByRole('button', { name: '保存' }).evaluate(
      (element) => getComputedStyle(element).backgroundColor
    )
    expect(modalPrimaryStyle).toBe('rgb(24, 61, 55)')
    await page.screenshot({
      path: join(auditRoot, 'student-editor.png'),
      fullPage: false
    })
  }

  if (testInfo.project.name === 'mobile-390') {
    const chartRow = page.locator('.school-chart-row').first()
    await expect(chartRow).toBeVisible()
    const scrollState = await chartRow.evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth
    }))
    expect(scrollState.scrollWidth).toBeGreaterThan(scrollState.clientWidth)

    await page.goto('/app/school-admin/students')
    await settlePage(page)
    const firstStudentRow = page.locator('.management-table tbody tr').first()
    await expect(firstStudentRow).toBeVisible()
    expect(await firstStudentRow.evaluate((element) => getComputedStyle(element).display)).toBe('block')
  }

  const report = {
    viewport: testInfo.project.name,
    reviewedRoutes: routes.map((route) => route.path),
    pageErrors,
    serverErrors,
    externalRequests: [...externalRequests],
    layoutFindings
  }
  writeFileSync(join(auditRoot, 'findings.json'), JSON.stringify(report, null, 2), 'utf8')

  expect(pageErrors, JSON.stringify(report, null, 2)).toEqual([])
  expect(serverErrors, JSON.stringify(report, null, 2)).toEqual([])
  expect([...externalRequests], JSON.stringify(report, null, 2)).toEqual([])
  expect(layoutFindings, JSON.stringify(report, null, 2)).toEqual([])
})
