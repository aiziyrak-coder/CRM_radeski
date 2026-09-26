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
  { path: '/', labelKey: 'nav.home', roles: ALL },
  { path: '/tasks', labelKey: 'nav.tasks', roles: ['operator', 'supervisor', 'admin'] },
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

export function navFor(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role))
}
