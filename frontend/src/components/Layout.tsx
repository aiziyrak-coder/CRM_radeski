import { useQuery } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  BarChart3,
  CalendarDays,
  CircleUser,
  ClipboardList,
  History,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Megaphone,
  Menu,
  MessagesSquare,
  PhoneCall,
  Plug,
  Settings,
  ShieldCheck,
  Stethoscope,
  UserCog,
  UserPlus,
  Users,
  X,
} from 'lucide-react'
import { Suspense, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, Outlet } from 'react-router'
import AlertsBell from './AlertsBell'
import PageErrorBoundary from './ErrorBoundary'
import GlobalSearch from './GlobalSearch'
import { api, type Language, type User } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import { getUnread } from '../lib/messaging'
import { NAV_GROUPS, navFor } from '../lib/navigation'
import { getTaskSummary } from '../lib/ops'
import { SoftphoneProvider } from '../lib/softphone'
import { CallPanel, SoftphoneStatus } from './Softphone'
import { Avatar, Badge, Button } from './ui'
import { cx } from '../lib/cx'

const ICONS: Record<string, LucideIcon> = {
  '/': LayoutDashboard,
  '/tasks': ListChecks,
  '/inbox': MessagesSquare,
  '/calls': PhoneCall,
  '/leads': UserPlus,
  '/patients': Users,
  '/schedule': CalendarDays,
  '/my-day': Stethoscope,
  '/diagnoses': ClipboardList,
  '/campaigns': Megaphone,
  '/qa': ShieldCheck,
  '/reports': BarChart3,
  '/users': UserCog,
  '/audit': History,
  '/integrations': Plug,
  '/settings': Settings,
  '/profile': CircleUser,
}

function Counter({ n, tone = 'teal' }: { n: number | undefined; tone?: 'teal' | 'red' }) {
  if (!n) return null
  return (
    <span
      className={cx(
        'ml-auto rounded-full px-1.5 py-px text-[11px] font-semibold tabular-nums',
        tone === 'red' ? 'bg-red-100 text-red-700' : 'bg-teal-100 text-teal-800',
      )}
    >
      {n > 99 ? '99+' : n}
    </span>
  )
}

function Sidebar({ onNavigate }: { onNavigate: () => void }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const items = user ? navFor(user.role) : []
  const has = (path: string) => items.some((i) => i.path === path)
  const { data: unread } = useQuery({
    queryKey: ['inbox', 'unread'],
    queryFn: getUnread,
    enabled: has('/inbox'),
    refetchInterval: 30_000,
  })
  const { data: summary } = useQuery({
    queryKey: ['tasks', 'summary'],
    queryFn: getTaskSummary,
    enabled: has('/tasks'),
    refetchInterval: 30_000,
  })
  if (!user) return null
  const counters: Record<string, { n?: number; tone?: 'teal' | 'red' }> = {
    '/inbox': { n: unread?.conversations },
    '/tasks': { n: summary?.total_due, tone: summary?.overdue ? 'red' : 'teal' },
    '/leads': { n: summary?.lead_sla_breached, tone: 'red' },
  }
  return (
    <>
      <Link to="/" onClick={onNavigate} className="flex items-center gap-3 px-5 py-4">
        <span className="flex size-9 items-center justify-center rounded-xl bg-teal-700 text-sm font-bold text-white shadow-sm">
          R
        </span>
        <span>
          <span className="block text-[15px] leading-tight font-semibold text-slate-900">
            {t('app.title')}
          </span>
          <span className="block text-xs text-slate-500">{t('app.clinic')}</span>
        </span>
      </Link>
      <nav className="flex-1 space-y-5 overflow-y-auto px-3 pb-4">
        {NAV_GROUPS.filter((g) => g !== 'me').map((group) => {
          const groupItems = items.filter((i) => i.group === group)
          if (!groupItems.length) return null
          return (
            <div key={group}>
              <div className="px-3 pb-1 text-[11px] font-semibold tracking-wider text-slate-400 uppercase">
                {t(`navGroups.${group}`)}
              </div>
              <div className="space-y-0.5">
                {groupItems.map((item) => {
                  const Icon = ICONS[item.path] ?? LayoutDashboard
                  const c = counters[item.path]
                  return (
                    <NavLink
                      key={item.path}
                      to={item.path}
                      end={item.path === '/'}
                      onClick={onNavigate}
                      className={({ isActive }) =>
                        cx(
                          'group flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors',
                          isActive
                            ? 'bg-teal-700 font-medium text-white shadow-sm'
                            : 'text-slate-700 hover:bg-slate-100',
                        )
                      }
                    >
                      {({ isActive }) => (
                        <>
                          <Icon
                            className={cx(
                              'size-4 shrink-0',
                              isActive ? 'text-white' : 'text-slate-400 group-hover:text-slate-600',
                            )}
                            aria-hidden
                          />
                          <span className="truncate">{t(item.labelKey)}</span>
                          {item.soon && <Badge>{t('soon.badge')}</Badge>}
                          {c && !isActive && <Counter n={c.n} tone={c.tone} />}
                        </>
                      )}
                    </NavLink>
                  )
                })}
              </div>
            </div>
          )
        })}
      </nav>
      <NavLink
        to="/profile"
        onClick={onNavigate}
        className={({ isActive }) =>
          cx(
            'flex items-center gap-3 border-t border-slate-200 px-4 py-3',
            isActive ? 'bg-teal-50' : 'hover:bg-slate-50',
          )
        }
      >
        <Avatar name={user.full_name} size="sm" />
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium text-slate-900">{user.full_name}</span>
          <span className="block text-xs text-slate-500">{t(`roles.${user.role}`)}</span>
        </span>
      </NavLink>
    </>
  )
}

export default function Layout() {
  const { t, i18n } = useTranslation()
  const { user, logout, setUser } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  if (!user) return null

  const switchLanguage = async (lang: Language) => {
    await i18n.changeLanguage(lang)
    try {
      setUser(await api<User>('/auth/me', { method: 'PATCH', body: { language: lang } }))
    } catch {
      // UI language already switched; profile will sync next time
    }
  }
  const otherLang: Language = i18n.language === 'uz' ? 'ru' : 'uz'
  const closeMenu = () => setMenuOpen(false)
  const canSearch = navFor(user.role).some((i) => i.path === '/patients')

  return (
    <SoftphoneProvider>
      <div className="flex min-h-screen bg-slate-50 text-slate-900">
        {/* desktop: fixed sidebar; tablet/phone: slide-over opened from the header */}
        <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-slate-200 bg-white lg:flex">
          <Sidebar onNavigate={closeMenu} />
        </aside>
        {menuOpen && (
          <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true">
            <button
              className="absolute inset-0 bg-slate-900/40"
              aria-label={t('app.close')}
              onClick={closeMenu}
            />
            <aside className="relative flex h-full w-72 flex-col bg-white shadow-xl">
              <button
                className="absolute top-4 right-3 rounded-md p-1.5 text-slate-500 hover:bg-slate-100"
                aria-label={t('app.close')}
                onClick={closeMenu}
              >
                <X className="size-4" aria-hidden />
              </button>
              <Sidebar onNavigate={closeMenu} />
            </aside>
          </div>
        )}

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-slate-200 bg-white/90 px-4 py-2.5 backdrop-blur lg:px-6">
            <button
              className="rounded-md p-2 text-slate-700 hover:bg-slate-100 lg:hidden"
              aria-label={t('app.menu')}
              onClick={() => setMenuOpen(true)}
            >
              <Menu className="size-5" aria-hidden />
            </button>
            {canSearch ? (
              <div className="hidden min-w-0 flex-1 md:block">
                <GlobalSearch />
              </div>
            ) : (
              <span className="font-semibold text-teal-800 lg:hidden">{t('app.title')}</span>
            )}
            <div className="ml-auto flex items-center gap-2">
              <AlertsBell />
              <SoftphoneStatus />
              <Button variant="ghost" size="sm" onClick={() => void switchLanguage(otherLang)}>
                {t(`lang.${otherLang}`)}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                icon={LogOut}
                onClick={() => void logout()}
                aria-label={t('auth.logout')}
              >
                <span className="hidden sm:inline">{t('auth.logout')}</span>
              </Button>
            </div>
          </header>
          <main className="mx-auto w-full max-w-[1400px] flex-1 p-4 lg:p-8">
            <Suspense fallback={<p className="text-sm text-slate-500">{t('app.loading')}</p>}>
              <PageErrorBoundary>
                <Outlet />
              </PageErrorBoundary>
            </Suspense>
          </main>
        </div>
        <CallPanel />
      </div>
    </SoftphoneProvider>
  )
}
