import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  formatPrice,
  getAllServices,
  getDoctorServiceLinks,
  getServiceCategories,
  serviceName,
  setDoctorServices,
  type Doctor,
  type ServiceItem,
} from '../lib/scheduling'
import { Button, ErrorText, Input, Notice } from './ui'

/**
 * TZ 4.2 "qaysi shifokor qaysi xizmatni bajaradi". A service with explicit links is offered only
 * with the linked doctors; a service nobody is linked to goes to every doctor of its specialty.
 */
export default function DoctorServicesEditor({ doctor, canEdit }: { doctor: Doctor; canEdit: boolean }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const services = useQuery({ queryKey: ['services', 'all'], queryFn: getAllServices, staleTime: 300_000 })
  const categories = useQuery({
    queryKey: ['service-categories'],
    queryFn: getServiceCategories,
    staleTime: 300_000,
  })
  const links = useQuery({ queryKey: ['doctor-services'], queryFn: () => getDoctorServiceLinks() })
  const [picked, setPicked] = useState<Set<string> | null>(null)
  const [q, setQ] = useState('')
  const [onlyMine, setOnlyMine] = useState(false)
  const [openCats, setOpenCats] = useState<Set<string>>(new Set())

  const mine = useMemo(
    () => new Set((links.data ?? []).filter((l) => l.doctor_id === doctor.id).map((l) => l.service_id)),
    [links.data, doctor.id],
  )
  // how many *other* doctors are linked to each service
  const others = useMemo(() => {
    const m = new Map<string, number>()
    for (const l of links.data ?? [])
      if (l.doctor_id !== doctor.id) m.set(l.service_id, (m.get(l.service_id) ?? 0) + 1)
    return m
  }, [links.data, doctor.id])
  const selected = picked ?? mine
  const dirty = picked !== null && (picked.size !== mine.size || [...picked].some((id) => !mine.has(id)))

  const save = useMutation({
    mutationFn: () => setDoctorServices(doctor.id, [...selected]),
    onSuccess: () => {
      setPicked(null)
      void queryClient.invalidateQueries({ queryKey: ['doctor-services'] })
    },
  })

  const catById = new Map((categories.data ?? []).map((c) => [c.id, c]))
  const bySpecialty = (s: ServiceItem) => {
    const spec = s.category_id ? catById.get(s.category_id)?.specialty : null
    return Boolean(spec && doctor.specialties.includes(spec))
  }
  const needle = q.trim().toLowerCase()
  const visible = (services.data ?? []).filter(
    (s) =>
      (!needle || s.name_uz.toLowerCase().includes(needle) || s.name_ru.toLowerCase().includes(needle)) &&
      (!onlyMine || selected.has(s.id)),
  )
  const groups = new Map<string, ServiceItem[]>()
  for (const s of visible) {
    const key = s.category_id ?? 'none'
    groups.set(key, [...(groups.get(key) ?? []), s])
  }
  const catName = (id: string) => {
    const c = catById.get(id)
    return c ? (i18n.language === 'ru' ? c.name_ru : c.name_uz) : t('links.noCategory')
  }
  const sortedGroups = [...groups].sort(([a], [b]) => catName(a).localeCompare(catName(b)))
  // services nobody was linked to: checking them takes them away from the specialty's other doctors
  const newlyExclusive = [...selected].filter((id) => !mine.has(id) && !others.get(id))

  const toggle = (ids: string[], on: boolean) => {
    const next = new Set(selected)
    for (const id of ids) {
      if (on) next.add(id)
      else next.delete(id)
    }
    setPicked(next)
    save.reset()
  }

  if (services.isPending || links.isPending)
    return <p className="text-sm text-slate-500">{t('app.loading')}</p>
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">
          {t('links.title')} <span className="text-sm font-normal text-slate-500">({selected.size})</span>
        </h3>
      </div>
      <p className="text-xs text-slate-500">{t('links.rule')}</p>
      <div className="flex flex-wrap gap-2">
        <Input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t('booking.searchService')}
          className="min-w-0 flex-1 sm:w-72 sm:flex-none"
        />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} />
          {t('links.onlyLinked')}
        </label>
      </div>
      {sortedGroups.length === 0 && <p className="text-sm text-slate-500">{t('links.none')}</p>}
      <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
        {sortedGroups.map(([catId, items]) => {
          const on = items.filter((s) => selected.has(s.id)).length
          const expanded = Boolean(needle) || openCats.has(catId)
          return (
            <li key={catId}>
              <div className="flex flex-wrap items-center gap-2 px-3 py-2">
                <button
                  className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm font-medium"
                  onClick={() => {
                    const next = new Set(openCats)
                    if (next.has(catId)) next.delete(catId)
                    else next.add(catId)
                    setOpenCats(next)
                  }}
                  aria-expanded={expanded}
                >
                  <span className="text-xs text-slate-400">{expanded ? '▼' : '▶'}</span>
                  <span className="truncate">{catName(catId)}</span>
                  <span className="shrink-0 text-xs font-normal text-slate-500">
                    {on}/{items.length}
                  </span>
                </button>
                {canEdit && (
                  <span className="flex gap-1">
                    <Button
                      variant="ghost"
                      className="px-2 py-0.5 text-xs"
                      onClick={() =>
                        toggle(
                          items.map((s) => s.id),
                          true,
                        )
                      }
                    >
                      {t('links.all')}
                    </Button>
                    <Button
                      variant="ghost"
                      className="px-2 py-0.5 text-xs"
                      onClick={() =>
                        toggle(
                          items.map((s) => s.id),
                          false,
                        )
                      }
                    >
                      {t('links.clear')}
                    </Button>
                  </span>
                )}
              </div>
              {expanded && (
                <ul className="border-t border-slate-100 bg-slate-50/50">
                  {items.map((s) => (
                    <li key={s.id}>
                      <label className="flex items-start gap-2 px-3 py-1.5 text-sm">
                        <input
                          type="checkbox"
                          className="mt-1"
                          disabled={!canEdit}
                          checked={selected.has(s.id)}
                          onChange={(e) => toggle([s.id], e.target.checked)}
                        />
                        <span className="min-w-0 flex-1">
                          {serviceName(s, i18n.language)}
                          <span className="ml-2 text-xs text-slate-500">
                            {s.duration_min}′ · {formatPrice(s.price)}
                          </span>
                          {!selected.has(s.id) && (others.get(s.id) ?? 0) > 0 && (
                            <span className="ml-2 text-xs text-slate-500">
                              {t('links.others', { count: others.get(s.id) })}
                            </span>
                          )}
                          {!selected.has(s.id) && !others.get(s.id) && bySpecialty(s) && (
                            <span className="ml-2 rounded bg-slate-100 px-1.5 text-xs text-slate-600">
                              {t('links.bySpecialty')}
                            </span>
                          )}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          )
        })}
      </ul>
      {canEdit && (
        <div className="space-y-2">
          {dirty && newlyExclusive.length > 0 && (
            <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {t('links.exclusiveWarning', { count: newlyExclusive.length })}
            </p>
          )}
          <div className="flex gap-2">
            <Button disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              {t('settings.save')}
            </Button>
            {dirty && (
              <Button variant="ghost" onClick={() => setPicked(null)}>
                {t('patients.cancel')}
              </Button>
            )}
          </div>
          {save.isSuccess && <Notice>{t('settings.saved')}</Notice>}
          <ErrorText error={save.error} />
        </div>
      )}
      <ErrorText error={services.error ?? links.error ?? categories.error} />
    </div>
  )
}
