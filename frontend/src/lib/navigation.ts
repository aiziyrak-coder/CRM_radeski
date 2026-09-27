import type { Role } from './api'

export type NavItem = {
  path: string
  labelKey: string
  roles: readonly Role[]
  /** module is planned but not built yet (shows a placeholder page) */
  soon?: boolean
}

const ALL: readonly Role[] = ['operator', 'supervisor', 'registrar', 'doctor', 'owner', 'admin']

// Single source of truth for the menu and route guards (backend enforces the same roles on its API).
export const NAV_ITEMS: readonly NavItem[] = [
  // the registrar starts on the schedule's "today" screen instead (see landingFor)
  { path: '/', labelKey: 'nav.home', roles: ALL.filter((r) => r !== 'registrar') },
  { path: '/tasks', labelKey: 'nav.tasks', roles: ['operator', 'supervisor', 'admin'] },
  { path: '/inbox', labelKey: 'nav.inbox', roles: ['operator', 'supervisor', 'registrar', 'admin'] },
  { path: '/calls', labelKey: 'nav.calls', roles: ['operator', 'supervisor', 'owner', 'admin'] },
  { path: '/leads', labelKey: 'nav.leads', roles: ['operator', 'supervisor', 'registrar', 'admin'] },
  {
    path: '/patients',
    labelKey: 'nav.patients',
    roles: ['operator', 'supervisor', 'registrar', 'admin'],
  },
  {
    path: '/schedule',
    labelKey: 'nav.schedule',
    roles: ['operator', 'supervisor', 'registrar', 'admin'],
  },
  { path: '/my-day', labelKey: 'nav.myDay', roles: ['doctor'] },
  { path: '/diagnoses', labelKey: 'nav.diagnoses', roles: ['doctor', 'supervisor', 'admin'] },
  { path: '/campaigns', labelKey: 'nav.campaigns', roles: ['supervisor', 'admin'] },
  { path: '/qa', labelKey: 'nav.qa', roles: ['supervisor', 'owner', 'admin'] },
  { path: '/reports', labelKey: 'nav.reports', roles: ['operator', 'supervisor', 'owner', 'admin'] },
  { path: '/users', labelKey: 'nav.users', roles: ['admin'] },
  { path: '/audit', labelKey: 'nav.audit', roles: ['admin', 'owner'] },
  { path: '/settings', labelKey: 'nav.settings', roles: ['supervisor', 'admin'] },
  { path: '/profile', labelKey: 'nav.profile', roles: ALL },
]

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
