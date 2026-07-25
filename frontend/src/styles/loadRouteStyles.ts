type RouteStyleGroup = 'resources' | 'learning' | 'governance' | 'assessments' | 'teacher' | 'student' | 'super-admin' | 'school-admin' | 'public'

const styleLoaders: Record<RouteStyleGroup, () => Promise<unknown>> = {
  resources: () => import('./resources.css'),
  learning: () => import('./learning-and-classroom.css'),
  governance: () => import('./data-governance.css'),
  assessments: () => import('./assessments.css'),
  teacher: () => import('./teacher-theme.css'),
  student: () => import('./student-theme.css'),
  'super-admin': () => import('./super-admin-theme.css'),
  'school-admin': () => import('./school-admin-theme.css'),
  public: () => import('./public-pages.css')
}

const loadingStyles = new Map<RouteStyleGroup, Promise<unknown>>()

export function styleGroupsForPath(path: string): RouteStyleGroup[] {
  if (path.startsWith('/super-admin')) return ['governance', 'super-admin']
  if (path.startsWith('/school-admin')) {
    return ['governance', 'resources', 'assessments', 'super-admin', 'school-admin']
  }
  if (path.startsWith('/teacher')) {
    return ['resources', 'learning', 'assessments', 'teacher']
  }
  if (path.startsWith('/student')) {
    return ['resources', 'learning', 'assessments', 'student']
  }
  if (path.startsWith('/learning-pages')) return ['learning', 'assessments']
  return ['public']
}

export async function loadRouteStyles(path: string) {
  const groups = styleGroupsForPath(path)
  await Promise.all(groups.map((group) => {
    const existing = loadingStyles.get(group)
    if (existing) return existing
    const loading = styleLoaders[group]()
    loadingStyles.set(group, loading)
    return loading
  }))
}
