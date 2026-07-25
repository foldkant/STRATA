import { expect, type Page } from '@playwright/test'

export type RoleName = 'superAdmin' | 'schoolAdmin' | 'teacher' | 'student'

const credentialNames: Record<RoleName, [string, string]> = {
  superAdmin: ['E2E_SUPER_ADMIN_USERNAME', 'E2E_SUPER_ADMIN_PASSWORD'],
  schoolAdmin: ['E2E_SCHOOL_ADMIN_USERNAME', 'E2E_SCHOOL_ADMIN_PASSWORD'],
  teacher: ['E2E_TEACHER_USERNAME', 'E2E_TEACHER_PASSWORD'],
  student: ['E2E_STUDENT_USERNAME', 'E2E_STUDENT_PASSWORD']
}

export function credentials(role: RoleName) {
  const [usernameKey, passwordKey] = credentialNames[role]
  const username = process.env[usernameKey] || ''
  const password = process.env[passwordKey] || ''
  return { username, password, available: Boolean(username && password) }
}

export async function login(page: Page, role: RoleName) {
  const account = credentials(role)
  if (!account.available) {
    throw new Error(`Missing E2E credentials for ${role}.`)
  }
  await page.goto('/login/')
  await page.locator('input[autocomplete="username"]').fill(account.username)
  await page.locator('input[autocomplete="current-password"]').fill(account.password)
  await Promise.all([
    page.waitForURL(/\/app\/(super-admin|school-admin|teacher|student)(?:\/|$)/),
    page.getByRole('button', { name: '登录并进入平台', exact: true }).click()
  ])
  await expect(page.locator('body')).not.toContainText('账号或密码不正确')
}

export async function settlePage(page: Page) {
  await page.waitForLoadState('domcontentloaded')
  await page.locator('#app').waitFor({ state: 'visible' })
  // Allow the first authenticated API requests to settle before assertions and screenshots.
  await page.waitForTimeout(1_200)
}
