import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import CampaignForm from '../components/CampaignForm'
import { ProgressBar, SegmentChips, StatusActions } from '../components/CampaignParts'
import { Badge, Button, Card, ErrorText } from '../components/ui'
import {
  STATUS_TONE,
  getCampaignList,
  getSuggestions,
  toInput,
  type Campaign,
  type CampaignInput,
  type CampaignStatus,
  type Suggestion,
} from '../lib/campaigns'
import { categoryName, getCategories, type Category } from '../lib/diagnoses'

const STATUSES: CampaignStatus[] = ['active', 'paused', 'draft', 'finished']

function Suggestions({ onPick }: { onPick: (input: CampaignInput) => void }) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(true)
  const { data: categories = [] } = useQuery({
    queryKey: ['diagnoses', 'categories'],
    queryFn: getCategories,
  })
  const suggestionTitle = (s: Suggestion) => {
    if (!s.code.startsWith('category:')) return t(`campaigns.suggest.${s.code}`)
    const c = categories.find((x) => x.code === s.categories?.[0])
    return t('campaigns.suggest.category', { name: c ? categoryName(c, i18n.language) : s.categories?.[0] })
  }
  const { data, error, isLoading } = useQuery({
    queryKey: ['campaigns', 'suggestions'],
    queryFn: getSuggestions,
    staleTime: 300_000,
  })
  return (
    <Card
      title={t('campaigns.suggest.title')}
      actions={
        <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setOpen(!open)}>
          {open ? t('campaigns.suggest.hide') : t('campaigns.suggest.show')}
        </Button>
      }
    >
      {open && (
        <>
          <p className="mb-3 text-xs text-slate-500">{t('campaigns.suggest.hint')}</p>
          <ErrorText error={error} />
          {isLoading && <p className="text-sm text-slate-500">{t('app.loading')}</p>}
          {data?.length === 0 && <p className="text-sm text-slate-500">{t('campaigns.suggest.none')}</p>}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {data?.map((s) => {
              const title = suggestionTitle(s)
              return (
                <div key={s.code} className="flex flex-col rounded-lg border border-slate-200 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="font-medium">{title}</div>
                      <div className="mt-0.5 text-xs text-slate-600">
                        {t(`campaigns.suggest.why.${s.code.startsWith('category:') ? 'category' : s.code}`, {
                          months: Math.round(s.days / 30),
                          specialty: s.specialty ? t(`diagnoses.specialties.${s.specialty}`) : '',
                        })}
                      </div>
                    </div>
                    {s.priority >= 9 && (
                      <span className="shrink-0 whitespace-nowrap">
                        <Badge>{t('campaigns.suggest.last')}</Badge>
                      </span>
                    )}
                  </div>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span className="text-xl font-semibold tabular-nums">{s.audience}</span>
                    <span className="text-xs text-slate-500">
                      {t('campaigns.suggest.days', { count: Math.ceil(s.audience / 30) })}
                    </span>
                  </div>
                  <div className="mt-2">
                    <SegmentChips segment={s.segment} categories={categories} />
                  </div>
                  <div className="mt-auto flex items-center justify-between gap-2 pt-3">
                    {s.campaign ? (
                      <span className="text-xs text-amber-800">
                        {t('campaigns.suggest.running', { name: s.campaign })}
                      </span>
                    ) : (
                      <span />
                    )}
                    <Button
                      variant="secondary"
                      className="px-2 py-1 text-xs"
                      onClick={() =>
                        onPick(toInput({ name: title, segment: s.segment, script_code: s.script_code }))
                      }
                    >
                      {t('campaigns.suggest.use')}
                    </Button>
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}
    </Card>
  )
}

function Num({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div>
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className="font-semibold tabular-nums">{value ?? '—'}</div>
    </div>
  )
}

function CampaignCard({ c, categories }: { c: Campaign; categories: Category[] }) {
  const { t } = useTranslation()
  const r = c.results
  const p = c.progress
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link to={`/campaigns/${c.id}`} className="font-semibold text-teal-800 hover:underline">
              {c.name}
            </Link>
            <Badge tone={STATUS_TONE[c.status]}>{t(`campaigns.statuses.${c.status}`)}</Badge>
            {c.ab && <Badge tone="info">A/B</Badge>}
          </div>
          {c.description && <p className="mt-0.5 line-clamp-2 text-xs text-slate-600">{c.description}</p>}
          <div className="mt-2">
            <SegmentChips segment={c.segment} categories={categories} />
          </div>
        </div>
        <StatusActions c={c} compact />
      </div>
      <div className="mt-3">
        <div className="mb-1 flex flex-wrap justify-between gap-2 text-xs text-slate-600">
          <span>
            {t('campaigns.progressLine', { done: p.tasked, total: p.audience, percent: p.percent })}
          </span>
          <span>
            {p.days_left !== null && c.status !== 'finished'
              ? t('campaigns.daysLeft', { count: p.days_left, limit: c.daily_limit })
              : t('campaigns.limitLine', { limit: c.daily_limit })}
          </span>
        </div>
        <ProgressBar percent={p.percent} />
      </div>
      <div className="mt-3 grid grid-cols-3 gap-3 text-sm sm:grid-cols-6">
        <Num label={t('campaigns.kpi.calls')} value={r.calls} />
        <Num label={t('campaigns.kpi.dialRate')} value={r.dial_rate === null ? null : `${r.dial_rate}%`} />
        <Num label={t('campaigns.kpi.booked')} value={r.booked} />
        <Num label={t('campaigns.kpi.arrived')} value={r.arrived} />
        <Num label={t('campaigns.kpi.refused')} value={r.outcomes.refused ?? 0} />
        <Num label={t('campaigns.kpi.today')} value={`${r.today.tasks}/${c.daily_limit}`} />
      </div>
    </li>
  )
}

export default function CampaignsPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [form, setForm] = useState<CampaignInput | null>(null)
  const [status, setStatus] = useState<CampaignStatus | ''>('')
  const { data: categories = [] } = useQuery({
    queryKey: ['diagnoses', 'categories'],
    queryFn: getCategories,
  })
  const {
    data: campaigns,
    error,
    isLoading,
  } = useQuery({
    queryKey: ['campaigns', 'list'],
    queryFn: () => getCampaignList(),
  })
  const counts = Object.fromEntries(
    STATUSES.map((s) => [s, campaigns?.filter((c) => c.status === s).length ?? 0]),
  )
  const shown = campaigns?.filter((c) => !status || c.status === status)
  const pick = (input: CampaignInput) => {
    setForm(input)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="max-w-6xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t('campaigns.title')}</h1>
        {!form && <Button onClick={() => pick(toInput())}>{t('campaigns.new')}</Button>}
      </div>
      {form && (
        <CampaignForm
          key={JSON.stringify(form)}
          initial={form}
          title={t('campaigns.new')}
          onDone={(id) => {
            setForm(null)
            if (id) navigate(`/campaigns/${id}`)
          }}
        />
      )}
      {!form && <Suggestions onPick={pick} />}

      <div className="flex flex-wrap gap-1.5">
        <Button
          variant={status === '' ? 'primary' : 'secondary'}
          className="px-2.5 py-1 text-xs"
          onClick={() => setStatus('')}
        >
          {t('campaigns.allStatuses')} ({campaigns?.length ?? 0})
        </Button>
        {STATUSES.map((s) => (
          <Button
            key={s}
            variant={status === s ? 'primary' : 'secondary'}
            className="px-2.5 py-1 text-xs"
            onClick={() => setStatus(s)}
          >
            {t(`campaigns.statuses.${s}`)} ({counts[s]})
          </Button>
        ))}
      </div>
      <ErrorText error={error} />
      {isLoading && <p className="text-sm text-slate-500">{t('app.loading')}</p>}
      {campaigns && campaigns.length === 0 && (
        <Card>
          <p className="text-sm text-slate-600">{t('campaigns.emptyHint')}</p>
        </Card>
      )}
      {shown && shown.length === 0 && campaigns && campaigns.length > 0 && (
        <p className="text-sm text-slate-500">{t('campaigns.emptyFilter')}</p>
      )}
      <ul className="space-y-3">
        {shown?.map((c) => (
          <CampaignCard key={c.id} c={c} categories={categories} />
        ))}
      </ul>
    </div>
  )
}
