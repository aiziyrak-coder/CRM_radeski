import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  createCampaign,
  getAudience,
  getCampaignTags,
  updateCampaign,
  type Bucket,
  type CampaignInput,
  type Segment,
} from '../lib/campaigns'
import { categoryName, getCategories } from '../lib/diagnoses'
import { getScripts } from '../lib/ops'
import { KINDS, getDistricts, type PatientKind, type Source } from '../lib/patients'
import { MultiChips } from './CampaignParts'
import { Button, Card, ErrorText, Field, Input, Select } from './ui'

const ALL_SOURCES: Source[] = [
  'instagram',
  'telegram',
  'google',
  'maps',
  'website',
  'recommendation',
  'advertising',
  'returning',
  'import',
  'cold_base',
  'other',
]

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(id)
  }, [value, ms])
  return v
}

function Bars({
  title,
  rows,
  label,
}: {
  title: string
  rows: Bucket[]
  label: (key: string | null) => string
}) {
  const max = Math.max(1, ...rows.map((r) => r.count))
  if (rows.length === 0) return null
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-slate-500 uppercase">{title}</div>
      <ul className="space-y-1">
        {rows.map((r) => (
          <li key={r.key ?? '∅'} className="grid grid-cols-[minmax(0,1fr)_3.5rem] items-center gap-2 text-xs">
            <div className="relative min-w-0 overflow-hidden rounded bg-slate-50">
              <div
                className="absolute inset-y-0 left-0 bg-teal-100"
                style={{ width: `${(100 * r.count) / max}%` }}
              />
              <span className="relative block truncate px-1.5 py-0.5 text-slate-800">{label(r.key)}</span>
            </div>
            <span className="text-right tabular-nums">{r.count}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function AudiencePanel({ segment, limit }: { segment: Segment; limit: number }) {
  const { t, i18n } = useTranslation()
  const debounced = useDebounced(segment, 400)
  const { data: categories = [] } = useQuery({
    queryKey: ['diagnoses', 'categories'],
    queryFn: getCategories,
  })
  const { data, error, isFetching } = useQuery({
    queryKey: ['campaigns', 'audience', JSON.stringify(debounced)],
    queryFn: () => getAudience(debounced),
    staleTime: 60_000,
  })
  const other = t('campaigns.aud.other')
  return (
    <aside className="space-y-3 rounded-lg border border-slate-200 bg-slate-50/60 p-4">
      <div className={isFetching ? 'opacity-60' : ''}>
        <div className="text-xs text-slate-500">{t('campaigns.aud.title')}</div>
        <div className="text-3xl font-semibold tabular-nums">{data ? data.audience : '…'}</div>
        {data && data.audience > 0 && (
          <div className="text-xs text-slate-600">
            {t('campaigns.aud.days', { count: Math.ceil(data.audience / Math.max(limit, 1)), limit })}
          </div>
        )}
        {data && data.audience === 0 && (
          <p className="mt-1 text-xs text-amber-800">{t('campaigns.aud.empty')}</p>
        )}
      </div>
      <ErrorText error={error} />
      {data && data.audience > 0 && (
        <div className="space-y-3">
          <Bars
            title={t('campaigns.kinds')}
            rows={data.by_kind}
            label={(k) => (k ? t(`kinds.${k}`) : other)}
          />
          <Bars
            title={t('campaigns.aud.recency')}
            rows={data.by_recency}
            label={(k) => (k ? t(`campaigns.recency.${k}`) : other)}
          />
          <Bars
            title={t('campaigns.categories')}
            rows={data.by_category}
            label={(k) => {
              const c = categories.find((x) => x.code === k)
              return c ? categoryName(c, i18n.language) : (k ?? other)
            }}
          />
          <Bars
            title={t('campaigns.districts')}
            rows={data.by_district}
            label={(k) => k ?? t('campaigns.aud.noDistrict')}
          />
          <Bars
            title={t('campaigns.sources')}
            rows={data.by_source}
            label={(k) => (k ? t(`sources.${k}`) : t('campaigns.aud.noSource'))}
          />
        </div>
      )}
    </aside>
  )
}

/** ISO timestamp -> 'YYYY-MM-DD' of the clinic day (for a date input). */
function dayOf(iso: string | null): string {
  if (!iso) return ''
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Tashkent' }).format(new Date(iso))
}

export default function CampaignForm({
  id,
  initial,
  title,
  onDone,
}: {
  /** set when editing an existing campaign */
  id?: string
  initial: CampaignInput
  title: string
  onDone: (id: string) => void
}) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [form, setForm] = useState<CampaignInput>(initial)
  const segment = form.segment
  const { data: categories = [] } = useQuery({
    queryKey: ['diagnoses', 'categories'],
    queryFn: getCategories,
  })
  const { data: districts = [] } = useQuery({
    queryKey: ['districts'],
    queryFn: getDistricts,
    staleTime: Infinity,
  })
  const { data: tags = [] } = useQuery({
    queryKey: ['campaigns', 'tags'],
    queryFn: getCampaignTags,
    staleTime: 300_000,
  })
  const { data: scripts = [] } = useQuery({ queryKey: ['scripts'], queryFn: () => getScripts() })
  const lang = i18n.language === 'ru' ? 'ru' : 'uz'
  const codes = [...new Set(scripts.map((s) => s.code))]
  const scriptTitle = (code: string) =>
    scripts.find((s) => s.code === code && s.language === lang)?.title ?? code

  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, name: form.name.trim(), description: form.description?.trim() || null }
      return id ? updateCampaign(id, body) : createCampaign(body)
    },
    onSuccess: (c) => {
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      onDone(c.id)
    },
  })
  const set = (patch: Partial<CampaignInput>) => setForm((f) => ({ ...f, ...patch }))
  const seg = (patch: Partial<Segment>) => {
    const next: Segment = { ...segment, ...patch }
    for (const k of Object.keys(next) as (keyof Segment)[]) {
      const v = next[k]
      if (v === undefined || (Array.isArray(v) && v.length === 0)) delete next[k]
    }
    set({ segment: next })
  }
  const num = (v: string) => (v === '' ? undefined : Math.max(0, Number(v)))
  const usedCategories = categories.filter((c) => c.patients > 0 || segment.categories?.includes(c.code))

  return (
    <Card title={title}>
      <form
        className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <div className="min-w-0 space-y-4">
          <p className="text-xs text-slate-500">{t('campaigns.hint')}</p>
          <Field label={t('campaigns.name')}>
            <Input
              value={form.name}
              onChange={(e) => set({ name: e.target.value })}
              maxLength={255}
              required
            />
          </Field>
          <Field label={t('campaigns.description')} hint={t('campaigns.descriptionHint')}>
            <textarea
              value={form.description ?? ''}
              onChange={(e) => set({ description: e.target.value })}
              maxLength={2000}
              rows={2}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20"
            />
          </Field>

          <fieldset className="space-y-3 rounded-lg border border-slate-200 p-3">
            <legend className="px-1 text-sm font-semibold">{t('campaigns.segment')}</legend>
            <Field label={t('campaigns.kinds')}>
              <MultiChips
                options={KINDS}
                value={segment.kinds ?? []}
                onChange={(v) => seg({ kinds: v as PatientKind[] })}
                label={(v) => t(`kinds.${v}`)}
              />
            </Field>
            <Field label={t('campaigns.categories')}>
              {usedCategories.length === 0 ? (
                <p className="text-xs text-slate-500">{t('campaigns.noCategories')}</p>
              ) : (
                <MultiChips
                  options={usedCategories.map((c) => c.code)}
                  value={segment.categories ?? []}
                  onChange={(v) => seg({ categories: v })}
                  label={(v) => {
                    const c = categories.find((x) => x.code === v)
                    return c ? `${categoryName(c, i18n.language)} · ${c.patients}` : v
                  }}
                />
              )}
            </Field>
            {districts.length > 0 && (
              <Field label={t('campaigns.districts')}>
                <MultiChips
                  options={districts}
                  value={segment.districts ?? []}
                  onChange={(v) => seg({ districts: v })}
                  label={(v) => v}
                />
              </Field>
            )}
            <Field label={t('campaigns.sources')}>
              <MultiChips
                options={ALL_SOURCES}
                value={(segment.sources ?? []) as Source[]}
                onChange={(v) => seg({ sources: v })}
                label={(v) => t(`sources.${v}`)}
              />
            </Field>
            <Field
              label={t('campaigns.tags')}
              hint={tags.length === 0 ? t('campaigns.noTags') : t('campaigns.tagsHint')}
            >
              {tags.length > 0 && (
                <MultiChips
                  options={tags.map((x) => x.tag)}
                  value={segment.tags ?? []}
                  onChange={(v) => seg({ tags: v })}
                  label={(v) => `#${v} · ${tags.find((x) => x.tag === v)?.count ?? 0}`}
                />
              )}
            </Field>
            <div className="grid grid-cols-2 items-end gap-3 md:grid-cols-4">
              <Field label={t('campaigns.lastVisit')}>
                <Input
                  type="number"
                  min={1}
                  max={3650}
                  value={segment.last_visit_before_days ?? ''}
                  onChange={(e) => seg({ last_visit_before_days: num(e.target.value) || undefined })}
                />
              </Field>
              <Field label={t('campaigns.gender')}>
                <Select
                  value={segment.gender ?? ''}
                  onChange={(e) => seg({ gender: (e.target.value || undefined) as Segment['gender'] })}
                >
                  <option value="">{t('campaigns.any')}</option>
                  <option value="female">{t('genders.female')}</option>
                  <option value="male">{t('genders.male')}</option>
                </Select>
              </Field>
              <Field label={t('campaigns.ageMin')}>
                <Input
                  type="number"
                  min={0}
                  max={120}
                  value={segment.age_min ?? ''}
                  onChange={(e) => seg({ age_min: num(e.target.value) })}
                />
              </Field>
              <Field label={t('campaigns.ageMax')}>
                <Input
                  type="number"
                  min={0}
                  max={120}
                  value={segment.age_max ?? ''}
                  onChange={(e) => seg({ age_max: num(e.target.value) })}
                />
              </Field>
            </div>
          </fieldset>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4">
            <Field label={t('campaigns.script')}>
              <Select value={form.script_code ?? ''} onChange={(e) => set({ script_code: e.target.value })}>
                {codes.map((code) => (
                  <option key={code} value={code}>
                    {scriptTitle(code)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t('campaigns.scriptB')}>
              <Select
                value={form.script_code_b ?? ''}
                onChange={(e) => set({ script_code_b: e.target.value || null })}
              >
                <option value="">{t('campaigns.noAb')}</option>
                {codes
                  .filter((code) => code !== form.script_code)
                  .map((code) => (
                    <option key={code} value={code}>
                      {scriptTitle(code)}
                    </option>
                  ))}
              </Select>
            </Field>
            <Field label={t('campaigns.dailyLimit')} hint={t('campaigns.dailyLimitHint')}>
              <Input
                type="number"
                min={1}
                max={500}
                value={form.daily_limit}
                onChange={(e) =>
                  set({ daily_limit: Math.min(500, Math.max(1, Number(e.target.value) || 1)) })
                }
              />
            </Field>
            <Field label={t('campaigns.endsOn')} hint={t('campaigns.endsOnHint')}>
              <Input
                type="date"
                value={dayOf(form.ends_on)}
                onChange={(e) => set({ ends_on: e.target.value ? `${e.target.value}T23:59:59+05:00` : null })}
              />
            </Field>
          </div>
          <ErrorText error={save.error} />
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" onClick={() => onDone(id ?? '')}>
              {t('patients.cancel')}
            </Button>
            <Button type="submit" disabled={form.name.trim().length < 2 || save.isPending}>
              {id ? t('campaigns.save') : t('campaigns.create')}
            </Button>
          </div>
        </div>
        <AudiencePanel segment={segment} limit={form.daily_limit} />
      </form>
    </Card>
  )
}
