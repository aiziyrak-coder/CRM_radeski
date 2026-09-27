import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Button, Card, ErrorText, Field, Input, Select } from '../components/ui'
import { api } from '../lib/api'
import { formatDateTime } from '../lib/patients'

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
type Facets = {
  actions: { action: string; count: number }[]
  entities: string[]
  users: { id: string; name: string; role: string }[]
}
type Filters = {
  group: string
  action: string
  user_id: string
  entity: string
  entity_id: string
  date_from: string
  date_to: string
}

const PAGE = 50
const EMPTY: Filters = {
  group: '',
  action: '',
  user_id: '',
  entity: '',
  entity_id: '',
  date_from: '',
  date_to: '',
}
// detail pages an audit row can open
const ENTITY_LINK: Record<string, (id: string) => string> = {
  patient: (id) => `/patients/${id}`,
  campaign: (id) => `/campaigns/${id}`,
  lead: (id) => `/leads?lead=${id}`,
}

function show(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'string') return v
  return JSON.stringify(v)
}

type Row = { key: string; before?: unknown; after?: unknown; changed: boolean }

/** before/after side by side; unchanged keys are listed too (dimmed) when both sides exist */
function diffRows(item: AuditItem): Row[] {
  const keys = [...new Set([...Object.keys(item.before ?? {}), ...Object.keys(item.after ?? {})])]
  return keys.map((key) => {
    const before = item.before?.[key]
    const after = item.after?.[key]
    return { key, before, after, changed: JSON.stringify(before) !== JSON.stringify(after) }
  })
}

function summary(item: AuditItem): string {
  const rows = diffRows(item)
  if (item.before) {
    const changed = rows.filter((r) => r.changed)
    return changed.map((r) => `${r.key}: ${show(r.before)} → ${show(r.after)}`).join('; ')
  }
  return rows
    .slice(0, 4)
    .map((r) => `${r.key}: ${show(r.after)}`)
    .join('; ')
}

function Diff({ item }: { item: AuditItem }) {
  const { t } = useTranslation()
  const rows = diffRows(item)
  if (rows.length === 0) return <p className="text-xs text-slate-500">{t('audit.noData')}</p>
  const both = Boolean(item.before && item.after)
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[480px] text-left text-xs">
        <thead className="text-slate-500">
          <tr>
            <th className="w-40 pb-1 font-medium">{t('audit.field')}</th>
            {item.before && <th className="pb-1 font-medium">{t('audit.before')}</th>}
            {item.after && <th className="pb-1 font-medium">{t('audit.after')}</th>}
          </tr>
        </thead>
        <tbody className="font-mono">
          {rows.map((r) => (
            <tr
              key={r.key}
              className={`border-t border-slate-100 align-top ${both && !r.changed ? 'text-slate-400' : ''}`}
            >
              <td className="py-1 pr-3 font-sans font-medium">{r.key}</td>
              {item.before && (
                <td className={`py-1 pr-3 break-all ${both && r.changed ? 'bg-red-50 text-red-900' : ''}`}>
                  {show(r.before)}
                </td>
              )}
              {item.after && (
                <td className={`py-1 break-all ${both && r.changed ? 'bg-emerald-50 text-emerald-900' : ''}`}>
                  {show(r.after)}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function AuditPage() {
  const { t } = useTranslation()
  const [draft, setDraft] = useState<Filters>(EMPTY)
  const [filters, setFilters] = useState<Filters>(EMPTY)
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState<string | null>(null)
  const { data: facets } = useQuery({
    queryKey: ['audit', 'facets'],
    queryFn: () => api<Facets>('/audit/facets'),
    staleTime: 300_000,
  })
  const qs = new URLSearchParams({ limit: String(PAGE), offset: String(offset) })
  for (const [k, v] of Object.entries(filters)) if (v.trim()) qs.set(k, v.trim())
  const { data, error, isFetching } = useQuery({
    queryKey: ['audit', qs.toString()],
    queryFn: () => api<AuditPage>(`/audit?${qs}`),
    placeholderData: keepPreviousData,
  })
  const label = (action: string) => t(`audit.actions.${action}`, { defaultValue: action })
  const groups = [...new Set((facets?.actions ?? []).map((a) => a.action.split('.')[0]))].sort()
  const apply = (next: Filters) => {
    setDraft(next)
    setFilters(next)
    setOffset(0)
    setOpen(null)
  }
  const set = (patch: Partial<Filters>) => apply({ ...draft, ...patch })
  const active = Object.values(filters).some(Boolean)

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{t('audit.title')}</h1>
        <p className="mt-1 text-sm text-slate-600">{t('audit.intro')}</p>
      </div>
      <Card>
        <form
          className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4"
          onSubmit={(e) => {
            e.preventDefault()
            apply(draft)
          }}
        >
          <Field label={t('audit.user')}>
            <Select value={draft.user_id} onChange={(e) => set({ user_id: e.target.value })}>
              <option value="">{t('audit.anyone')}</option>
              {facets?.users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} · {t(`roles.${u.role}`, { defaultValue: u.role })}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('audit.group')}>
            <Select value={draft.group} onChange={(e) => set({ group: e.target.value, action: '' })}>
              <option value="">{t('audit.anyGroup')}</option>
              {groups.map((g) => (
                <option key={g} value={g}>
                  {t(`audit.groups.${g}`, { defaultValue: g })}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('audit.action')}>
            <Select value={draft.action} onChange={(e) => set({ action: e.target.value })}>
              <option value="">{t('audit.anyAction')}</option>
              {facets?.actions
                .filter((a) => !draft.group || a.action.startsWith(`${draft.group}.`))
                .map((a) => (
                  <option key={a.action} value={a.action}>
                    {label(a.action)} ({a.count})
                  </option>
                ))}
            </Select>
          </Field>
          <Field label={t('audit.entity')}>
            <Select value={draft.entity} onChange={(e) => set({ entity: e.target.value })}>
              <option value="">{t('audit.anyEntity')}</option>
              {facets?.entities.map((en) => (
                <option key={en} value={en}>
                  {t(`audit.entities.${en}`, { defaultValue: en })}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('audit.entityId')} hint={t('audit.entityIdHint')}>
            <Input
              value={draft.entity_id}
              maxLength={64}
              onChange={(e) => setDraft({ ...draft, entity_id: e.target.value })}
              onBlur={() => draft.entity_id !== filters.entity_id && apply(draft)}
            />
          </Field>
          <Field label={t('audit.from')}>
            <Input type="date" value={draft.date_from} onChange={(e) => set({ date_from: e.target.value })} />
          </Field>
          <Field label={t('audit.to')}>
            <Input type="date" value={draft.date_to} onChange={(e) => set({ date_to: e.target.value })} />
          </Field>
          <div className="flex items-end gap-2">
            <Button type="submit" variant="secondary">
              {t('audit.apply')}
            </Button>
            {active && (
              <Button variant="ghost" onClick={() => apply(EMPTY)}>
                {t('audit.reset')}
              </Button>
            )}
          </div>
        </form>
      </Card>

      <Card
        actions={
          data && (
            <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
              <span>{t('audit.total', { count: data.total })}</span>
              {data.total > PAGE && (
                <span className="tabular-nums">
                  {offset + 1}–{Math.min(offset + PAGE, data.total)}
                </span>
              )}
              <Button
                variant="secondary"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE))}
              >
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
        {data?.total === 0 && (
          <p className="py-6 text-center text-sm text-slate-500">
            {active ? t('audit.emptyFiltered') : t('audit.empty')}
          </p>
        )}
        {data && data.total > 0 && (
          <div className={`overflow-x-auto ${isFetching ? 'opacity-60' : ''}`}>
            <table className="w-full min-w-[720px] text-left text-sm">
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
                {data.items.map((item) => {
                  const expanded = open === item.id
                  const link =
                    item.entity && item.entity_id ? ENTITY_LINK[item.entity]?.(item.entity_id) : null
                  const hasData = Boolean(item.before || item.after)
                  return (
                    <Fragment key={item.id}>
                      <tr className="border-t border-slate-100 align-top">
                        <td className="py-2 pr-4 whitespace-nowrap text-slate-600">
                          {formatDateTime(item.created_at)}
                        </td>
                        <td className="py-2 pr-4">{item.user_name ?? t('audit.system')}</td>
                        <td className="py-2 pr-4">
                          <div>{label(item.action)}</div>
                          {item.entity && (
                            <div className="text-xs text-slate-500">
                              {t(`audit.entities.${item.entity}`, { defaultValue: item.entity })}
                              {item.entity_id &&
                                (link ? (
                                  <>
                                    {' · '}
                                    <Link to={link} className="text-teal-800 hover:underline">
                                      {t('audit.open')}
                                    </Link>
                                  </>
                                ) : (
                                  <button
                                    type="button"
                                    className="ml-1 text-teal-800 hover:underline"
                                    title={item.entity_id}
                                    onClick={() => set({ entity: item.entity!, entity_id: item.entity_id! })}
                                  >
                                    {t('audit.sameObject')}
                                  </button>
                                ))}
                            </div>
                          )}
                        </td>
                        <td className="py-2 pr-4 text-slate-600">
                          <div className="line-clamp-2 break-words">{summary(item)}</div>
                          {hasData && (
                            <button
                              type="button"
                              className="text-xs text-teal-800 hover:underline"
                              aria-expanded={expanded}
                              onClick={() => setOpen(expanded ? null : item.id)}
                            >
                              {expanded ? t('audit.hide') : t('audit.showDiff')}
                            </button>
                          )}
                        </td>
                        <td className="py-2 text-xs text-slate-500">{item.ip}</td>
                      </tr>
                      {expanded && (
                        <tr>
                          <td colSpan={5} className="bg-slate-50 px-3 py-2">
                            <Diff item={item} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
