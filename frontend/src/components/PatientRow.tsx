import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { formatDate, type PatientListItem } from '../lib/patients'
import { Badge } from './ui'

export default function PatientRow({ p, action }: { p: PatientListItem; action?: ReactNode }) {
  const { t } = useTranslation()
  return (
    <tr className="border-t border-slate-100 align-top">
      <td className="py-2.5 pr-4">
        <Link to={`/patients/${p.id}`} className="font-medium text-teal-800 hover:underline">
          {p.full_name}
        </Link>
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
