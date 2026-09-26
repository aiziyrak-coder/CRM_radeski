import { useQuery } from '@tanstack/react-query'
import { Suspense, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet } from 'react-router'
import { api, type Language, type User } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import { getUnread } from '../lib/messaging'
import { navFor } from '../lib/navigation'
import { SoftphoneProvider } from '../lib/softphone'
import { CallPanel, SoftphoneStatus } from './Softphone'
import { Badge, Button } from './ui'

function Sidebar({ onNavigate }: { onNavigate: () => void }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const inbox = Boolean(user && navFor(user.role).some((i) => i.path === '/inbox'))
  const { data: unread } = useQuery({
    queryKey: ['inbox', 'unread'],
    queryFn: getUnread,
    enabled: inbox,
    refetchInterval: 30_000,
  })
  if (!user) return null
  return (
    <>
      <div className="border-b border-slate-200 px-5 py-4">
        <div className="text-lg font-semibold text-teal-800">{t('app.title')}</div>
        <div className="text-xs text-slate-500">{t('app.clinic')}</div>
      </div>
      <nav className="flex-1 space-y-0.5 overflow-y-auto p-3">
        {navFor(user.role).map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            onClick={onNavigate}
            className={({ isActive }) =>
              [
                'flex items-center justify-between rounded-md px-3 py-2 text-sm',
                isActive ? 'bg-teal-50 font-medium text-teal-800' : 'text-slate-700 hover:bg-slate-100',
              ].join(' ')
            }
          >
            <span>{t(item.labelKey)}</span>
            {item.soon && <Badge>{t('soon.badge')}</Badge>}
            {item.path === '/inbox' && (unread?.conversations ?? 0) > 0 && (
              <span className="rounded-full bg-teal-700 px-1.5 text-[11px] text-white tabular-nums">
                {unread!.conversations}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
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

  return (
    <SoftphoneProvider>
      <div className="flex min-h-screen bg-slate-50 text-slate-900">
        {/* desktop: fixed sidebar; tablet/phone: slide-over opened from the header */}
        <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-200 bg-white lg:flex">
          <Sidebar onNavigate={closeMenu} />
        </aside>
        {menuOpen && (
          <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true">
            <button
              className="absolute inset-0 bg-slate-900/40"
              aria-label={t('app.close')}
              onClick={closeMenu}
            />
            <aside className="relative flex h-full w-64 flex-col bg-white shadow-xl">
              <Sidebar onNavigate={closeMenu} />
            </aside>
          </div>
        )}

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3 lg:px-6">
            <button
              className="rounded-md p-2 text-slate-700 hover:bg-slate-100 lg:hidden"
              aria-label={t('app.menu')}
              onClick={() => setMenuOpen(true)}
            >
              <svg
                width="20"
                height="20"
                viewBox="0 0 20 20"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
              >
                <path d="M3 5h14M3 10h14M3 15h14" strokeLinecap="round" />
              </svg>
            </button>
            <span className="font-semibold text-teal-800 lg:hidden">{t('app.title')}</span>
            <div className="ml-auto flex items-center gap-3">
              <SoftphoneStatus />
              <div className="hidden text-right sm:block">
                <div className="text-sm font-medium">{user.full_name}</div>
                <div className="text-xs text-slate-500">{t(`roles.${user.role}`)}</div>
              </div>
              <Button variant="secondary" onClick={() => void switchLanguage(otherLang)}>
                {t(`lang.${otherLang}`)}
              </Button>
              <Button variant="ghost" onClick={() => void logout()}>
                {t('auth.logout')}
              </Button>
            </div>
          </header>
          <main className="flex-1 p-4 lg:p-6">
            <Suspense fallback={<p className="text-sm text-slate-500">{t('app.loading')}</p>}>
              <Outlet />
            </Suspense>
          </main>
        </div>
        <CallPanel />
      </div>
    </SoftphoneProvider>
  )
}
