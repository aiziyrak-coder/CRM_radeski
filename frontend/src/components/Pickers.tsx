import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { searchPatients, type PatientListItem } from '../lib/patients'
import { searchServices, serviceName, type ServiceItem } from '../lib/scheduling'
import PatientName from './PatientName'
import { Button, Input } from './ui'

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(id)
  }, [value, ms])
  return v
}

export function PatientPicker({
  value,
  onChange,
}: {
  value: PatientListItem | null
  onChange: (p: PatientListItem | null) => void
}) {
  const { t } = useTranslation()
  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const { data } = useQuery({
    queryKey: ['patients', 'picker', dq],
    queryFn: () => searchPatients({ q: dq, offset: 0, limit: 8 }),
    enabled: !value && dq.trim().length >= 2,
  })

  if (value) {
    return (
      <div className="flex items-center justify-between rounded-md border border-slate-200 px-3 py-2">
        <div>
          <div className="font-medium">
            <PatientName name={value.full_name} />
          </div>
          <div className="text-xs text-slate-500">{value.phones.map((p) => p.display).join(', ')}</div>
        </div>
        <Button variant="ghost" onClick={() => onChange(null)}>
          {t('booking.change')}
        </Button>
      </div>
    )
  }
  return (
    <div>
      <Input
        type="search"
        placeholder={t('booking.pickPatient')}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        autoFocus
      />
      {data && data.items.length > 0 && (
        <ul className="mt-1 max-h-56 overflow-y-auto rounded-md border border-slate-200">
          {data.items.map((p) => (
            <li key={p.id}>
              <button
                className="w-full px-3 py-2 text-left text-sm hover:bg-slate-50"
                onClick={() => {
                  onChange(p)
                  setQ('')
                }}
              >
                <PatientName name={p.full_name} />{' '}
                <span className="text-xs text-slate-500">{p.phones[0]?.display}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function ServicePicker({
  value,
  onChange,
}: {
  value: ServiceItem[]
  onChange: (s: ServiceItem[]) => void
}) {
  const { t, i18n } = useTranslation()
  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const { data } = useQuery({
    queryKey: ['services', 'picker', dq],
    queryFn: () => searchServices({ q: dq, limit: 10 }),
    enabled: dq.trim().length >= 2,
  })
  const minutes = value.reduce((sum, s) => sum + s.duration_min, 0)

  return (
    <div className="space-y-2">
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((s) => (
            <span
              key={s.id}
              className="inline-flex items-center gap-1 rounded-full bg-teal-50 px-2.5 py-1 text-xs text-teal-900"
            >
              {serviceName(s, i18n.language)}
              <button
                aria-label="remove"
                className="text-teal-700"
                onClick={() => onChange(value.filter((x) => x.id !== s.id))}
              >
                ✕
              </button>
            </span>
          ))}
          <span className="px-1 py-1 text-xs text-slate-500">{t('booking.duration', { min: minutes })}</span>
        </div>
      )}
      <Input
        type="search"
        placeholder={t('booking.searchService')}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {data && data.items.length > 0 && (
        <ul className="max-h-56 overflow-y-auto rounded-md border border-slate-200">
          {data.items
            .filter((s) => !value.some((v) => v.id === s.id))
            .map((s) => (
              <li key={s.id}>
                <button
                  className="flex w-full justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-slate-50"
                  onClick={() => {
                    onChange([...value, s])
                    setQ('')
                  }}
                >
                  <span>{serviceName(s, i18n.language)}</span>
                  <span className="shrink-0 text-xs text-slate-500">{s.duration_min}′</span>
                </button>
              </li>
            ))}
        </ul>
      )}
    </div>
  )
}
