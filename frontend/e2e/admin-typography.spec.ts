import { expect, test } from '@playwright/test'
import { login, settlePage, type RoleName } from './helpers'

const workspaces: Array<{
  role: RoleName
  home: string
  densePage: string
  shell: string
}> = [
  {
    role: 'superAdmin',
    home: '/app/super-admin',
    densePage: '/app/super-admin/curriculum-standards',
    shell: '.app-shell-super-admin'
  },
  {
    role: 'schoolAdmin',
    home: '/app/school-admin',
    densePage: '/app/school-admin/students',
    shell: '.app-shell-school-admin'
  }
]

for (const workspace of workspaces) {
  test(`${workspace.role} uses the calibrated local governance typography`, async ({ page }, testInfo) => {
    const externalRequests = new Set<string>()
    page.on('request', (request) => {
      const url = new URL(request.url())
      if (!['127.0.0.1', 'localhost'].includes(url.hostname)) externalRequests.add(url.origin)
    })

    await login(page, workspace.role)
    await page.goto(workspace.home)
    await settlePage(page)
    await page.evaluate(() => document.fonts.ready)

    const homeTypography = await page.locator(workspace.shell).evaluate((shell) => {
      const navLink = shell.querySelector<HTMLElement>('.nav-group a')
      const topbarTitle = shell.querySelector<HTMLElement>('.topbar h1')
      const pageTitle = shell.querySelector<HTMLElement>('.super-admin-page-heading h2')
      return {
        shellFamily: getComputedStyle(shell).fontFamily,
        navSize: navLink ? Number.parseFloat(getComputedStyle(navLink).fontSize) : 0,
        topbarSize: topbarTitle ? Number.parseFloat(getComputedStyle(topbarTitle).fontSize) : 0,
        pageTitleSize: pageTitle ? Number.parseFloat(getComputedStyle(pageTitle).fontSize) : 0,
        fontReady: document.fonts.check('16px "STRATA WenKai UI"'),
        overflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth)
      }
    })

    expect(homeTypography.shellFamily).toContain('STRATA WenKai UI')
    expect(homeTypography.fontReady).toBe(true)
    expect(homeTypography.navSize).toBeGreaterThanOrEqual(14)
    expect(homeTypography.topbarSize).toBeGreaterThanOrEqual(20)
    expect(homeTypography.pageTitleSize).toBeGreaterThanOrEqual(27)
    expect(homeTypography.overflow).toBeLessThanOrEqual(1)

    await page.screenshot({ path: testInfo.outputPath(`${workspace.role}-home.png`), fullPage: true })

    await page.goto(workspace.densePage)
    await settlePage(page)
    await page.evaluate(() => document.fonts.ready)

    const denseTypography = await page.locator(workspace.shell).evaluate((shell) => {
      const tableHeading = shell.querySelector<HTMLElement>('th')
      const contentHeading = shell.querySelector<HTMLElement>(
        '.curriculum-reading-guide > header strong, .management-panel .panel-heading h2'
      )
      return {
        tableHeadingSize: tableHeading ? Number.parseFloat(getComputedStyle(tableHeading).fontSize) : null,
        contentHeadingFamily: contentHeading ? getComputedStyle(contentHeading).fontFamily : '',
        overflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth)
      }
    })

    if (denseTypography.tableHeadingSize !== null) {
      expect(denseTypography.tableHeadingSize).toBeGreaterThanOrEqual(14)
    }
    expect(denseTypography.contentHeadingFamily).toContain('STRATA WenKai UI')
    expect(denseTypography.overflow).toBeLessThanOrEqual(1)
    expect([...externalRequests]).toEqual([])

    await page.screenshot({ path: testInfo.outputPath(`${workspace.role}-dense.png`), fullPage: true })
  })
}
