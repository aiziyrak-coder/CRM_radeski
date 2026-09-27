import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { ageOf, formatDate, type PatientListItem } from '../lib/patients'
import PatientName from './PatientName'
import PatientTags from './PatientTags'
import { Badge } from './ui'

/** Compact row (duplicate warnings, merge search). */
export default function PatientRow({ p, action }: { p: PatientListItem; action?: ReactNode }) {
  const { t } = useTranslation()
  return (
    <tr className="border-t border-slate-100 align-top">
      <td className="py-2.5 pr-4">
        <Link to={`/patients/${p.id}`} className="font-medium text-teal-800 hover:underline">
          <PatientName name={p.full_name} />
        </Link>
        <span className="ml-2">
          <PatientTags tags={p.tags} />
        </span>
        {p.do_not_call && (
          <span className="ml-2">
            <Badge tone="bad">{t('patients.dnc')}</Badge>
          </span>
        )}
      </td>
      <td className="py-2.5 pr-4 whitespace-nowrap">{p.phones.map((ph) => ph.display).join(', ')}</td>
      <td className="py-2.5 pr-4 whitespace-nowrap">{formatDate(p.birth_date)}</td>
      <td className="py-2.5 pr-4">{p.district ?? '—'}</td>
      <td className="py-2.5 pr-4">
        <Badge tone={p.kind === 'active' ? 'good' : 'neutral'}>{t(`kinds.${p.kind}`)}</Badge>
      </td>
      {action !== undefined && <td className="py-2.5 text-right">{action}</td>}
    </tr>
  )
}

function Categories({ codes, nameOf }: { codes: string[]; nameOf: (code: string) => string }) {
  if (codes.length === 0) return <span className="text-slate-400">—</span>
  const shown = codes.slice(0, 2)
  return (
    <span className="inline-flex flex-wrap gap-1" title={codes.map(nameOf).join(', ')}>
      {shown.map((c) => (
        <Badge key={c} tone="good">
          {nameOf(c)}
        </Badge>
      ))}
      {codes.length > shown.length && <Badge>+{codes.length - shown.length}</Badge>}
    </span>
  )
}

const primaryPhone = (p: PatientListItem) => p.phones.find((ph) => ph.is_primary) ?? p.phones[0]

/** The patients list: every column the call center filters and sorts by. */
export function PatientTableRow({ p, nameOf }: { p: PatientListItem; nameOf: (code: string) => string }) {
  const { t } = useTranslation()
  const phone = primaryPhone(p)
  const age = ageOf(p.birth_date)
  return (
    <tr className="border-t border-slate-100 align-top hover:bg-slate-50">
      <td className="py-2.5 pr-3">
        <Link to={`/patients/${p.id}`} className="font-medium text-teal-800 hover:underline">
          <PatientName name={p.full_name} />
        </Link>
        <div className="mt-0.5 flex flex-wrap gap-1">
          <PatientTags tags={p.tags} />
          {p.do_not_call && <Badge tone="bad">{t('patients.dnc')}</Badge>}
        </div>
      </td>
      <td className="py-2.5 pr-3 whitespace-nowrap tabular-nums">
        {phone ? (
          <span className={phone.wrong_number_at ? 'text-slate-400 line-through' : undefined}>
            {phone.display}
          </span>
        ) : (
          <span className="text-xs text-red-700">{t('patientList.noPhone')}</span>
        )}
        {p.phones.length > 1 && <span className="ml-1 text-xs text-slate-500">+{p.phones.length - 1}</span>}
      </td>
      <td className="py-2.5 pr-3">
        <Badge tone={p.kind === 'active' ? 'good' : 'neutral'}>{t(`kinds.${p.kind}`)}</Badge>
      </td>
      <td className="py-2.5 pr-3 tabular-nums" title={formatDate(p.birth_date)}>
        {age ?? '—'}
      </td>
      <td className="py-2.5 pr-3">{p.district ?? '—'}</td>
      <td className="py-2.5 pr-3">
        <Categories codes={p.categories ?? []} nameOf={nameOf} />
      </td>
      <td className="py-2.5 pr-3 whitespace-nowrap tabular-nums">
        {p.last_visit_at ? formatDate(p.last_visit_at) : '—'}
      </td>
      <td className="py-2.5 pr-3 whitespace-nowrap tabular-nums">
        {p.next_visit_at ? (
          <span className="font-medium text-teal-800">{formatDate(p.next_visit_at)}</span>
        ) : (
          '—'
        )}
      </td>
      <td className="py-2.5 pr-3">{p.source ? t(`sources.${p.source}`) : '—'}</td>
    </tr>
  )
}

/** Phone-width version of the same row. */
export function PatientListCard({ p, nameOf }: { p: PatientListItem; nameOf: (code: string) => string }) {
  const { t } = useTranslation()
  const phone = primaryPhone(p)
  const age = ageOf(p.birth_date)
  return (
    <li className="border-t border-slate-100 py-3 first:border-t-0">
      <div className="flex items-start justify-between gap-2">
        <Link
          to={`/patients/${p.id}`}
          className="min-w-0 font-medium break-words text-teal-800 hover:underline"
        >
          <PatientName name={p.full_name} />
        </Link>
        <Badge tone={p.kind === 'active' ? 'good' : 'neutral'}>{t(`kinds.${p.kind}`)}</Badge>
      </div>
      <div className="mt-1 text-sm text-slate-700 tabular-nums">
        {phone ? phone.display : <span className="text-xs text-red-700">{t('patientList.noPhone')}</span>}
        {age !== null && <span className="text-slate-500"> · {t('patientList.years', { count: age })}</span>}
        {p.district && <span className="text-slate-500"> · {p.district}</span>}
      </div>
      <div className="mt-1 flex flex-wrap gap-1">
        <PatientTags tags={p.tags} />
        {p.do_not_call && <Badge tone="bad">{t('patients.dnc')}</Badge>}
        {(p.categories ?? []).length > 0 && <Categories codes={p.categories ?? []} nameOf={nameOf} />}
      </div>
      <div className="mt-1 text-xs text-slate-500">
        {t('patients.lastVisit')}: {p.last_visit_at ? formatDate(p.last_visit_at) : '—'}
        {p.next_visit_at && (
          <span className="text-teal-800">
            {' '}
            · {t('patientList.nextVisit')}: {formatDate(p.next_visit_at)}
          </span>
        )}
      </div>
    </li>
  )
}
