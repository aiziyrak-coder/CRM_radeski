import type { Role } from './api'

export type NavGroup = 'work' | 'clinic' | 'growth' | 'admin' | 'me'

export type NavItem = {
  path: string
  labelKey: string
  roles: readonly Role[]
  /** sidebar section (the menu is grouped so 15 items stay readable) */
  group: NavGroup
  /** module is planned but not built yet (shows a placeholder page) */
  soon?: boolean
}

const ALL: readonly Role[] = ['operator', 'supervisor', 'registrar', 'doctor', 'owner', 'admin']

// Single source of truth for the menu and route guards (backend enforces the same roles on its API).
export const NAV_ITEMS: readonly NavItem[] = [
  // the registrar starts on the schedule's "today" screen instead (see landingFor)
  { path: '/', group: 'work', labelKey: 'nav.home', roles: ALL.filter((r) => r !== 'registrar') },
  { path: '/tasks', group: 'work', labelKey: 'nav.tasks', roles: ['operator', 'supervisor', 'admin'] },
  {
    path: '/inbox',
    group: 'work',
    labelKey: 'nav.inbox',
    roles: ['operator', 'supervisor', 'registrar', 'admin'],
  },
  {
    path: '/calls',
    group: 'work',
    labelKey: 'nav.calls',
    roles: ['operator', 'supervisor', 'owner', 'admin'],
  },
  {
    path: '/leads',
    group: 'work',
    labelKey: 'nav.leads',
    roles: ['operator', 'supervisor', 'registrar', 'admin'],
  },
  {
    path: '/patients',
    group: 'clinic',
    labelKey: 'nav.patients',
    roles: ['operator', 'supervisor', 'registrar', 'admin'],
  },
  {
    path: '/schedule',
    group: 'clinic',
    labelKey: 'nav.schedule',
    roles: ['operator', 'supervisor', 'registrar', 'admin'],
  },
  { path: '/my-day', group: 'clinic', labelKey: 'nav.myDay', roles: ['doctor'] },
  {
    path: '/diagnoses',
    group: 'clinic',
    labelKey: 'nav.diagnoses',
    roles: ['doctor', 'supervisor', 'admin'],
  },
  { path: '/campaigns', group: 'growth', labelKey: 'nav.campaigns', roles: ['supervisor', 'admin'] },
  { path: '/qa', group: 'growth', labelKey: 'nav.qa', roles: ['supervisor', 'owner', 'admin'] },
  {
    path: '/reports',
    group: 'growth',
    labelKey: 'nav.reports',
    roles: ['operator', 'supervisor', 'owner', 'admin'],
  },
  { path: '/users', group: 'admin', labelKey: 'nav.users', roles: ['admin'] },
  { path: '/audit', group: 'admin', labelKey: 'nav.audit', roles: ['admin', 'owner'] },
  { path: '/integrations', group: 'admin', labelKey: 'nav.integrations', roles: ['admin'] },
  { path: '/settings', group: 'admin', labelKey: 'nav.settings', roles: ['supervisor', 'admin'] },
  { path: '/profile', group: 'me', labelKey: 'nav.profile', roles: ALL },
]

export const NAV_GROUPS: readonly NavGroup[] = ['work', 'clinic', 'growth', 'admin', 'me']

export const ROLES: readonly Role[] = ALL

/** Where a role lands after login (and when a page isn't open to it). TZ 4.3 "Registrator ekrani". */
export function landingFor(role: Role): string {
  return role === 'registrar' ? '/schedule' : '/'
}

export function navFor(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role))
}

/** Whether a link to this menu section (or a detail page under it) would open for the role. */
export function canOpen(role: Role | undefined, path: string): boolean {
  return Boolean(role && NAV_ITEMS.find((item) => item.path === path)?.roles.includes(role))
}
