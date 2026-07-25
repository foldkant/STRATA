import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { credentials, login, settlePage } from './helpers'

const routes = [
  { slug: 'dashboard', path: '/app/super-admin' },
  { slug: 'schools', path: '/app/super-admin/schools' },
  { slug: 'school-admins', path: '/app/super-admin/school-admins' },
  { slug: 'curriculum-standards', path: '/app/super-admin/curriculum-standards' },
  { slug: 'collection', path: '/app/super-admin/collection' },
  { slug: 'analysis', path: '/app/super-admin/analysis' },
  { slug: 'health', path: '/app/super-admin/health' }
]

test('super administrator pages share one visual language and remain operable', async ({ page }, testInfo) => {
  test.skip(!credentials('superAdmin').available, 'Set super administrator E2E credentials.')

  const auditRoot = join(
    '..',
    'docs',
    'ui-self-check',
    'super-admin-review-2026-07-24',
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

  await login(page, 'superAdmin')
  for (const route of routes) {
    await page.goto(route.path)
    await settlePage(page)
    await expect(page.locator('.app-shell-super-admin')).toBeVisible()
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

  if (testInfo.project.name === 'desktop-1440') {
    await page.goto('/app/super-admin/curriculum-standards')
    await settlePage(page)
    const informationTechnologyStandard = page
      .locator('.curriculum-list > button')
      .filter({ hasText: '普通高中信息科技课程标准' })
      .first()
    await expect(informationTechnologyStandard).toBeVisible()
    await informationTechnologyStandard.click()
    await expect(page.getByRole('button', { name: '逐页原文核对' })).toBeVisible()
    await page.getByRole('button', { name: '逐页原文核对' }).click()

    const guidance = page.locator('.curriculum-page-guidance')
    await expect(guidance).toBeVisible()
    await expect(guidance.getByText('当前版本已发布')).toBeVisible()
    await expect(page.locator('.curriculum-page-list > article').first()).toBeVisible()
    const guidanceStyle = await guidance.evaluate((element) => {
      const style = getComputedStyle(element)
      return {
        backgroundColor: style.backgroundColor,
        borderLeftColor: style.borderLeftColor,
        borderRadius: style.borderRadius
      }
    })
    expect(guidanceStyle.backgroundColor).not.toBe('rgb(239, 246, 255)')
    expect(guidanceStyle.borderLeftColor).not.toBe('rgb(191, 219, 254)')
    await page.screenshot({
      path: join(auditRoot, 'curriculum-page-review.png'),
      fullPage: false
    })

    await page.getByRole('button', { name: '关闭', exact: true }).first().click()
    await page.getByRole('button', { name: '登记课程标准' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.screenshot({
      path: join(auditRoot, 'curriculum-standard-editor.png'),
      fullPage: false
    })
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
