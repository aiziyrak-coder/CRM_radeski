import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from './lib/api'

type Readiness = Record<'db' | 'redis', string>

export default function App() {
  const { t, i18n } = useTranslation()
  const { data, isPending, isError } = useQuery({
    queryKey: ['health', 'ready'],
    queryFn: () => apiGet<Readiness>('/health/ready'),
    refetchInterval: 15_000,
  })

  const toggleLang = () => void i18n.changeLanguage(i18n.language === 'uz' ? 'ru' : 'uz')

  return (
    <main className="min-h-screen bg-slate-50 p-6 text-slate-900">
      <header className="mx-auto flex max-w-3xl items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('app.title')}</h1>
        <button
          onClick={toggleLang}
          className="rounded-md border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100"
        >
          {t('lang.switch')}
        </button>
      </header>

      <section className="mx-auto mt-8 max-w-3xl rounded-lg border border-slate-200 bg-white p-5">
        {isPending && <p>{t('health.checking')}</p>}
        {isError && <p className="text-red-600">{t('health.down')}</p>}
        {data && (
          <ul className="space-y-1">
            <li className="font-medium text-emerald-700">{t('health.ok')}</li>
            <li>
              {t('health.db')}: {data.db}
            </li>
            <li>
              {t('health.redis')}: {data.redis}
            </li>
          </ul>
        )}
      </section>
    </main>
  )
}
