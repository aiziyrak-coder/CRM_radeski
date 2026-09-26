import { NavLink, Outlet } from 'react-router'
import { useTranslation } from 'react-i18next'
import { api, type Language, type User } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import { navFor } from '../lib/navigation'
import { Badge, Button } from './ui'

export default function Layout() {
  const { t, i18n } = useTranslation()
  const { user, logout, setUser } = useAuth()
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

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900">
      <aside className="flex w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-5 py-4">
          <div className="text-lg font-semibold text-teal-800">{t('app.title')}</div>
          <div className="text-xs text-slate-500">{t('app.clinic')}</div>
        </div>
        <nav className="flex-1 space-y-0.5 p-3">
          {navFor(user.role).map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) =>
                [
                  'flex items-center justify-between rounded-md px-3 py-2 text-sm',
                  isActive ? 'bg-teal-50 font-medium text-teal-800' : 'text-slate-700 hover:bg-slate-100',
                ].join(' ')
              }
            >
              <span>{t(item.labelKey)}</span>
              {item.soon && <Badge>{t('soon.badge')}</Badge>}
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-end gap-3 border-b border-slate-200 bg-white px-6 py-3">
          <div className="text-right">
            <div className="text-sm font-medium">{user.full_name}</div>
            <div className="text-xs text-slate-500">{t(`roles.${user.role}`)}</div>
          </div>
          <Button variant="secondary" onClick={() => void switchLanguage(otherLang)}>
            {t(`lang.${otherLang}`)}
          </Button>
          <Button variant="ghost" onClick={() => void logout()}>
            {t('auth.logout')}
          </Button>
        </header>
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
