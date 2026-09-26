import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Card, ErrorText } from '../components/ui'
import { api } from '../lib/api'

type AuditItem = {
  id: string
  created_at: string
  user_id: string | null
  user_name: string | null
  action: string
  entity: string | null
  entity_id: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  ip: string | null
}
type AuditPage = { total: number; items: AuditItem[] }

const PAGE = 50

function describeChange(item: AuditItem): string {
  if (item.before && item.after) {
    return Object.keys(item.after)
      .filter((k) => JSON.stringify(item.before?.[k]) !== JSON.stringify(item.after?.[k]))
      .map((k) => `${k}: ${String(item.before?.[k])} → ${String(item.after?.[k])}`)
      .join('; ')
  }
  if (item.after) {
    return Object.entries(item.after)
      .filter(([k]) => ['username', 'full_name', 'role'].includes(k))
      .map(([k, v]) => `${k}: ${String(v)}`)
      .join('; ')
  }
  return ''
}

export default function AuditPage() {
  const { t, i18n } = useTranslation()
  const [offset, setOffset] = useState(0)
  const { data, error } = useQuery({
    queryKey: ['audit', offset],
    queryFn: () => api<AuditPage>(`/audit?limit=${PAGE}&offset=${offset}`),
    placeholderData: keepPreviousData,
  })
  const locale = i18n.language === 'ru' ? 'ru-RU' : 'uz-UZ'

  return (
    <div className="max-w-6xl space-y-6">
      <h1 className="text-2xl font-semibold">{t('audit.title')}</h1>
      <Card
        actions={
          data && (
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <span>{t('audit.total', { count: data.total })}</span>
              <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>
                {t('audit.prev')}
              </Button>
              <Button
                variant="secondary"
                disabled={offset + PAGE >= data.total}
                onClick={() => setOffset(offset + PAGE)}
              >
                {t('audit.next')}
              </Button>
            </div>
          )
        }
      >
        <ErrorText error={error} />
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-slate-500 uppercase">
            <tr>
              <th className="pb-2 font-medium">{t('audit.time')}</th>
              <th className="pb-2 font-medium">{t('audit.user')}</th>
              <th className="pb-2 font-medium">{t('audit.action')}</th>
              <th className="pb-2 font-medium">{t('audit.details')}</th>
              <th className="pb-2 font-medium">IP</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((item) => (
              <tr key={item.id} className="border-t border-slate-100 align-top">
                <td className="py-2 pr-4 whitespace-nowrap text-slate-600">
                  {new Date(item.created_at).toLocaleString(locale)}
                </td>
                <td className="py-2 pr-4">{item.user_name ?? t('audit.system')}</td>
                <td className="py-2 pr-4">{t(`audit.actions.${item.action}`, { defaultValue: item.action })}</td>
                <td className="py-2 pr-4 text-slate-600">{describeChange(item)}</td>
                <td className="py-2 text-xs text-slate-500">{item.ip}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}
