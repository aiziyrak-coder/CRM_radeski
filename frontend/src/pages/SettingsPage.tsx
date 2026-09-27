import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { useSearchParams } from 'react-router'
import DoctorServicesEditor from '../components/DoctorServicesEditor'
import ScriptsEditor from '../components/ScriptsEditor'
import TemplatesEditor from '../components/TemplatesEditor'
import WeeklyScheduleEditor from '../components/WeeklyScheduleEditor'
import { Badge, Button, Card, ErrorText, Field, Input, Notice, Select } from '../components/ui'
import { api, type User } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import type { Specialty } from '../lib/diagnoses'
import { formatDate, formatDateTime } from '../lib/patients'
import {
  ABSENCE_KINDS,
  addAbsence,
  branchName,
  bulkUpdateServices,
  createResource,
  deleteAbsence,
  doctorName,
  formatPrice,
  getBranches,
  getDeviceTypes,
  getDoctorSchedule,
  getDoctors,
  getResources,
  getServiceCategories,
  getSyncState,
  searchServices,
  serviceName,
  syncCatalog,
  updateDoctor,
  updateResource,
  updateService,
  type AbsenceKind,
  type Doctor,
  type Resource,
  type ServiceItem,
} from '../lib/scheduling'

/** Device types are codes chosen by the admin ("laser_epilation"); known ones get a name. */
const deviceName = (t: TFunction, code: string) =>
  t(`deviceTypes.${code}`, { defaultValue: code.replace(/_/g, ' ') })

const SPECIALTIES: Specialty[] = [
  'dermatologist',
  'trichologist',
  'cosmetologist',
  'oncodermatologist',
  'podologist',
]
const TABS = ['doctors', 'resources', 'services', 'scripts', 'templates'] as const
type Tab = (typeof TABS)[number]
const ABSENCE_TONE = { vacation: 'info', sick: 'bad', other: 'neutral' } as const

// --- catalog sync ---------------------------------------------------------------------------

function SyncInfo({ isAdmin }: { isAdmin: boolean }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const state = useQuery({ queryKey: ['catalog-sync'], queryFn: getSyncState })
  const sync = useMutation({
    mutationFn: syncCatalog,
    onSettled: () => void queryClient.invalidateQueries(),
  })
  const last = state.data?.last
  const ok = state.data?.last_ok
  const changes = Object.entries(ok?.counts ?? {}).filter(([, n]) => typeof n === 'number' && n > 0)
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3">
      <div className="min-w-0 text-sm">
        {!last ? (
          <p className="text-slate-600">{t('syncInfo.never')}</p>
        ) : (
          <>
            <p>
              {t('syncInfo.last')}: <span className="font-medium">{formatDateTime(last.finished_at)}</span>{' '}
              <Badge tone={last.status === 'ok' ? 'good' : 'bad'}>
                {t(`syncInfo.status.${last.status}`)}
              </Badge>{' '}
              <span className="text-xs text-slate-500">({t(`syncInfo.trigger.${last.trigger}`)})</span>
            </p>
            {last.status !== 'ok' && (
              <p className="mt-1 text-xs text-red-700">
                {last.status === 'aborted' ? t('errors.sync_aborted') : t('errors.site_unavailable')}
                {ok && ` · ${t('syncInfo.lastOk')}: ${formatDateTime(ok.finished_at)}`}
              </p>
            )}
            {last.status === 'ok' && changes.length > 0 && (
              <p className="mt-1 text-xs text-slate-500">
                {changes
                  .map(([k, n]) =>
                    t(`syncInfo.counts.${k}`, { count: Number(n), defaultValue: `${k}: ${n}` }),
                  )
                  .join(' · ')}
              </p>
            )}
          </>
        )}
        <p className="mt-1 text-xs text-slate-500">{t('syncInfo.daily')}</p>
      </div>
      {isAdmin && (
        <Button variant="secondary" disabled={sync.isPending} onClick={() => sync.mutate()}>
          {sync.isPending ? t('app.loading') : t('settings.sync')}
        </Button>
      )}
      <div className="w-full empty:hidden">
        {sync.isSuccess && <Notice>{t('settings.synced')}</Notice>}
        <ErrorText error={sync.error ?? state.error} />
      </div>
    </div>
  )
}

// --- doctors --------------------------------------------------------------------------------

function Absences({ doctorId, canEdit }: { doctorId: string; canEdit: boolean }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const schedule = useQuery({ queryKey: ['schedule', doctorId], queryFn: () => getDoctorSchedule(doctorId) })
  const empty = { date_from: '', date_to: '', kind: 'vacation' as AbsenceKind, reason: '' }
  const [absence, setAbsence] = useState(empty)
  const badRange = Boolean(absence.date_from && absence.date_to && absence.date_from > absence.date_to)
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['schedule', doctorId] })
    void queryClient.invalidateQueries({ queryKey: ['appointments'] })
  }
  const add = useMutation({
    mutationFn: () => addAbsence(doctorId, { ...absence, reason: absence.reason.trim() || null }),
    onSuccess: () => {
      setAbsence(empty)
      refresh()
    },
  })
  const del = useMutation({ mutationFn: deleteAbsence, onSuccess: refresh })
  const list = schedule.data?.absences ?? []
  return (
    <div>
      <h3 className="mb-2 font-medium">{t('settings.absences')}</h3>
      {list.length === 0 ? (
        <p className="mb-3 text-sm text-slate-500">{t('absence.none')}</p>
      ) : (
        <ul className="mb-3 divide-y divide-slate-100 rounded-md border border-slate-200 text-sm">
          {list.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
              <Badge tone={ABSENCE_TONE[a.kind]}>{t(`absenceKinds.${a.kind}`)}</Badge>
              <span className="tabular-nums">
                {formatDate(a.date_from)} — {formatDate(a.date_to)}
              </span>
              {a.reason && <span className="text-slate-500">{a.reason}</span>}
              {canEdit && (
                <Button
                  variant="ghost"
                  className="ml-auto px-2 py-0.5 text-xs"
                  disabled={del.isPending}
                  onClick={() => del.mutate(a.id)}
                  aria-label={t('app.remove')}
                >
                  ✕
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canEdit && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t('settings.kind')}>
            <Select
              value={absence.kind}
              onChange={(e) => setAbsence({ ...absence, kind: e.target.value as AbsenceKind })}
              className="w-36"
            >
              {ABSENCE_KINDS.map((k) => (
                <option key={k} value={k}>
                  {t(`absenceKinds.${k}`)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('settings.from')}>
            <Input
              type="date"
              value={absence.date_from}
              onChange={(e) =>
                setAbsence({
                  ...absence,
                  date_from: e.target.value,
                  date_to: absence.date_to || e.target.value,
                })
              }
            />
          </Field>
          <Field label={t('settings.to')}>
            <Input
              type="date"
              value={absence.date_to}
              min={absence.date_from || undefined}
              onChange={(e) => setAbsence({ ...absence, date_to: e.target.value })}
            />
          </Field>
          <Field label={t('settings.reason')}>
            <Input
              value={absence.reason}
              onChange={(e) => setAbsence({ ...absence, reason: e.target.value })}
              maxLength={255}
            />
          </Field>
          <Button
            variant="secondary"
            disabled={!absence.date_from || !absence.date_to || badRange || add.isPending}
            onClick={() => add.mutate()}
          >
            {t('settings.addAbsence')}
          </Button>
        </div>
      )}
      <p className="mt-2 text-xs text-slate-500">{t('absence.hint')}</p>
      {badRange && <p className="text-sm text-red-700">{t('errors.from_after_to')}</p>}
      <ErrorText error={add.error ?? del.error ?? schedule.error} />
    </div>
  )
}

function DoctorEditor({ doctor, isAdmin, canPlan }: { doctor: Doctor; isAdmin: boolean; canPlan: boolean }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [section, setSection] = useState<'schedule' | 'absences' | 'services'>('schedule')
  const { data: users = [] } = useQuery({
    queryKey: ['users'],
    queryFn: () => api<User[]>('/users'),
    enabled: isAdmin,
  })
  const schedule = useQuery({
    queryKey: ['schedule', doctor.id],
    queryFn: () => getDoctorSchedule(doctor.id),
  })
  // the colour picker fires on every drag step; keep it local (saved by the effect below)
  const [color, setColor] = useState(doctor.color ?? '#0f766e')

  const saveDoctor = useMutation({
    mutationFn: (body: Parameters<typeof updateDoctor>[1]) => updateDoctor(doctor.id, body),
    onSuccess: (saved) => {
      // the saved doctor goes straight into the list: a quick next click builds on it, not on
      // the pre-save props while the refetch is still running
      queryClient.setQueriesData<(typeof saved)[]>({ queryKey: ['doctors'] }, (list) =>
        Array.isArray(list) ? list.map((d) => (d.id === saved.id ? saved : d)) : list,
      )
      void queryClient.invalidateQueries({ queryKey: ['doctors'] })
    },
  })
  // saved shortly after the last change: blur is unreliable with native colour pickers
  const { mutate: saveDoctorNow } = saveDoctor
  const savedColor = doctor.color ?? '#0f766e'
  useEffect(() => {
    if (color === savedColor) return
    const timer = window.setTimeout(() => saveDoctorNow({ color }), 700)
    return () => window.clearTimeout(timer)
  }, [color, savedColor, saveDoctorNow])
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['schedule', doctor.id] })
    void queryClient.invalidateQueries({ queryKey: ['appointments'] })
  }
  const linked = users.find((u) => u.id === doctor.user_id)

  return (
    <div className="space-y-5">
      <div>
        <div className="flex flex-wrap items-center gap-2 text-lg font-semibold">
          {doctorName(doctor, i18n.language)}
          {!doctor.is_active && <Badge>{t('settings.inactive')}</Badge>}
        </div>
        <div className="text-sm text-slate-500">
          {i18n.language === 'ru' ? doctor.title_ru : doctor.title_uz}
        </div>
      </div>

      {isAdmin && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Field label={t('settings.specialties')}>
            <div className="space-y-1">
              {SPECIALTIES.map((s) => (
                <label key={s} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={doctor.specialties.includes(s)}
                    disabled={saveDoctor.isPending}
                    onChange={(e) =>
                      saveDoctor.mutate({
                        specialties: e.target.checked
                          ? [...doctor.specialties, s]
                          : doctor.specialties.filter((x) => x !== s),
                      })
                    }
                  />
                  {t(`diagnoses.specialties.${s}`)}
                </label>
              ))}
            </div>
          </Field>
          <Field label={t('settings.color')}>
            <Input
              type="color"
              value={color}
              onChange={(e) => setColor(e.target.value)}
              className="h-10 w-20 p-1"
            />
          </Field>
          <Field label={t('settings.linkUser')} hint={t('doctorx.linkHint')}>
            <Select
              value={doctor.user_id ?? ''}
              onChange={(e) => saveDoctor.mutate({ user_id: e.target.value || null })}
            >
              <option value="">{t('settings.noUser')}</option>
              {users
                .filter((u) => u.role === 'doctor')
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name} ({u.username})
                  </option>
                ))}
            </Select>
            {doctor.user_id && linked && !linked.is_active && (
              <span className="mt-1 block text-xs text-amber-800">{t('doctorx.userInactive')}</span>
            )}
          </Field>
          <label className="flex items-center gap-2 text-sm md:col-span-3">
            <input
              type="checkbox"
              checked={doctor.is_active}
              disabled={saveDoctor.isPending}
              onChange={(e) => saveDoctor.mutate({ is_active: e.target.checked })}
            />
            {t('doctorx.active')}
          </label>
        </div>
      )}
      <ErrorText error={saveDoctor.error} />

      <div className="flex gap-1 overflow-x-auto overflow-y-hidden border-b border-slate-200 whitespace-nowrap">
        {(['schedule', 'absences', 'services'] as const).map((k) => (
          <button
            key={k}
            onClick={() => setSection(k)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${section === k ? 'border-teal-700 font-medium text-teal-800' : 'border-transparent text-slate-600'}`}
          >
            {t(`doctorx.section.${k}`)}
          </button>
        ))}
      </div>

      {section === 'schedule' &&
        // fresh data only: the editor starts from it, a cached copy could overwrite newer changes
        (schedule.data && schedule.isFetchedAfterMount ? (
          <WeeklyScheduleEditor
            key={doctor.id}
            doctorId={doctor.id}
            initial={schedule.data.rows}
            canEdit={canPlan}
            onSaved={refresh}
          />
        ) : (
          <p className="text-sm text-slate-500">{t('app.loading')}</p>
        ))}
      {section === 'absences' && <Absences doctorId={doctor.id} canEdit={canPlan} />}
      {section === 'services' && <DoctorServicesEditor key={doctor.id} doctor={doctor} canEdit={isAdmin} />}
    </div>
  )
}

function DoctorsTab({ isAdmin, canPlan }: { isAdmin: boolean; canPlan: boolean }) {
  const { t, i18n } = useTranslation()
  const { data: doctors = [], isPending } = useQuery({
    queryKey: ['doctors', 'all'],
    queryFn: () => getDoctors(false),
  })
  const [selected, setSelected] = useState<string>('')
  const [q, setQ] = useState('')
  const [showInactive, setShowInactive] = useState(false)
  const doctor = doctors.find((d) => d.id === selected)
  const needle = q.trim().toLowerCase()
  const shown = doctors.filter(
    (d) =>
      (showInactive || d.is_active) &&
      (!needle || d.name_uz.toLowerCase().includes(needle) || d.name_ru.toLowerCase().includes(needle)),
  )
  if (!isPending && doctors.length === 0) {
    return <p className="text-sm text-slate-600">{t('doctorx.noDoctors')}</p>
  }
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[16rem_1fr]">
      <div className="space-y-2">
        <Input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t('doctorx.search')}
        />
        <label className="flex items-center gap-2 text-xs text-slate-600">
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
          {t('doctorx.showInactive')}
        </label>
        <ul className="max-h-[28rem] space-y-1 overflow-y-auto lg:max-h-none">
          {shown.map((d) => (
            <li key={d.id}>
              <button
                onClick={() => setSelected(d.id)}
                className={`w-full rounded-md px-3 py-2 text-left text-sm ${selected === d.id ? 'bg-teal-50 font-medium text-teal-900' : 'hover:bg-slate-100'}`}
              >
                {d.color && (
                  <span
                    className="mr-2 inline-block h-2.5 w-2.5 rounded-full"
                    style={{ background: d.color }}
                  />
                )}
                {doctorName(d, i18n.language)}
                {!d.is_active && (
                  <span className="ml-1">
                    <Badge>{t('settings.inactive')}</Badge>
                  </span>
                )}
                {isAdmin && !d.user_id && d.is_active && (
                  <span className="block text-xs font-normal text-slate-500">{t('doctorx.noLogin')}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="min-w-0">
        {doctor ? (
          <DoctorEditor key={doctor.id} doctor={doctor} isAdmin={isAdmin} canPlan={canPlan} />
        ) : (
          <p className="text-sm text-slate-500">{t('settings.pickDoctor')}</p>
        )}
      </div>
    </div>
  )
}

// --- rooms and devices -----------------------------------------------------------------------

type ResourceDraft = Omit<Resource, 'id'>

function ResourceForm({
  initial,
  onSave,
  onCancel,
  busy,
  deviceTypes,
}: {
  initial: ResourceDraft
  onSave: (r: ResourceDraft) => void
  onCancel?: () => void
  busy: boolean
  deviceTypes: string[]
}) {
  const { t, i18n } = useTranslation()
  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: getBranches,
    staleTime: 300_000,
  })
  const [draft, setDraft] = useState(initial)
  const branchId = draft.branch_id || branches.find((b) => b.is_main)?.id || branches[0]?.id || ''
  return (
    <div className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_9rem_12rem_12rem_auto]">
      <Input
        placeholder={t('settings.name')}
        value={draft.name}
        onChange={(e) => setDraft({ ...draft, name: e.target.value })}
        maxLength={100}
        aria-label={t('settings.name')}
      />
      <Select
        value={draft.kind}
        onChange={(e) => setDraft({ ...draft, kind: e.target.value as Resource['kind'] })}
        aria-label={t('settings.kind')}
      >
        <option value="device">{t('settings.device')}</option>
        <option value="room">{t('settings.room')}</option>
      </Select>
      <Input
        placeholder="laser_epilation"
        list="device-types"
        disabled={draft.kind !== 'device'}
        value={draft.kind === 'device' ? (draft.device_type ?? '') : ''}
        onChange={(e) =>
          setDraft({ ...draft, device_type: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '') })
        }
        aria-label={t('settings.deviceType')}
      />
      <datalist id="device-types">
        {deviceTypes.map((d) => (
          <option key={d} value={d} />
        ))}
      </datalist>
      <Select
        value={branchId}
        onChange={(e) => setDraft({ ...draft, branch_id: e.target.value })}
        aria-label={t('schedule.branch')}
      >
        {branches.map((b) => (
          <option key={b.id} value={b.id}>
            {branchName(b, i18n.language)}
          </option>
        ))}
      </Select>
      <div className="flex gap-1">
        <Button
          disabled={!draft.name.trim() || (draft.kind === 'device' && !draft.device_type) || busy}
          onClick={() =>
            onSave({
              ...draft,
              name: draft.name.trim(),
              branch_id: branchId,
              device_type: draft.kind === 'device' ? draft.device_type : null,
            })
          }
        >
          {onCancel ? t('settings.save') : t('settings.add')}
        </Button>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel}>
            {t('patients.cancel')}
          </Button>
        )}
      </div>
    </div>
  )
}

function ResourcesTab() {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: getBranches,
    staleTime: 300_000,
  })
  const { data: resources = [], isPending } = useQuery({
    queryKey: ['resources'],
    queryFn: () => getResources(),
  })
  const { data: deviceTypes = [] } = useQuery({ queryKey: ['device-types'], queryFn: getDeviceTypes })
  const [editing, setEditing] = useState<string | null>(null)
  const [branchFilter, setBranchFilter] = useState('')
  const [formKey, setFormKey] = useState(0)
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['resources'] })
    void queryClient.invalidateQueries({ queryKey: ['device-types'] })
  }
  const create = useMutation({
    mutationFn: createResource,
    onSuccess: () => {
      setFormKey((k) => k + 1)
      refresh()
    },
  })
  const save = useMutation({
    mutationFn: ({ id, body }: { id: string; body: ResourceDraft }) => updateResource(id, body),
    onSuccess: () => {
      setEditing(null)
      refresh()
    },
  })
  const branch = (id: string) => {
    const b = branches.find((x) => x.id === id)
    return b ? branchName(b, i18n.language) : ''
  }
  const typeNames = deviceTypes.map((d) => d.device_type)
  const shown = resources.filter((r) => !branchFilter || r.branch_id === branchFilter)
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">{t('resx.intro')}</p>
      {branches.length > 1 && (
        <Select
          value={branchFilter}
          onChange={(e) => setBranchFilter(e.target.value)}
          className="w-full sm:w-56"
        >
          <option value="">{t('usersx.allBranches')}</option>
          {branches.map((b) => (
            <option key={b.id} value={b.id}>
              {branchName(b, i18n.language)}
            </option>
          ))}
        </Select>
      )}
      {!isPending && shown.length === 0 && <p className="text-sm text-slate-500">{t('sched.noRooms')}</p>}
      {shown.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-xs text-slate-500 uppercase">
              <tr>
                <th className="pb-2">{t('settings.name')}</th>
                <th className="pb-2">{t('settings.kind')}</th>
                <th className="pb-2">{t('settings.deviceType')}</th>
                <th className="pb-2">{t('schedule.branch')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {shown.map((r) =>
                editing === r.id ? (
                  <tr key={r.id} className="border-t border-slate-100">
                    <td colSpan={5} className="py-2">
                      <ResourceForm
                        initial={r}
                        busy={save.isPending}
                        deviceTypes={typeNames}
                        onSave={(body) => save.mutate({ id: r.id, body })}
                        onCancel={() => setEditing(null)}
                      />
                    </td>
                  </tr>
                ) : (
                  <tr
                    key={r.id}
                    className={`border-t border-slate-100 ${r.is_active ? '' : 'text-slate-400'}`}
                  >
                    <td className="py-2 font-medium">{r.name}</td>
                    <td className="py-2">{t(`settings.${r.kind}`)}</td>
                    <td className="py-2 text-xs">{r.device_type ? deviceName(t, r.device_type) : '—'}</td>
                    <td className="py-2">{branch(r.branch_id)}</td>
                    <td className="py-2 text-right whitespace-nowrap">
                      <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setEditing(r.id)}>
                        {t('settings.edit')}
                      </Button>
                      <Button
                        variant={r.is_active ? 'secondary' : 'ghost'}
                        className="px-2 py-1 text-xs"
                        disabled={save.isPending}
                        onClick={() => save.mutate({ id: r.id, body: { ...r, is_active: !r.is_active } })}
                      >
                        {r.is_active ? t('settings.active') : t('settings.inactive')}
                      </Button>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
      <div className="rounded-md bg-slate-50 p-3">
        <h3 className="mb-2 text-sm font-medium">{t('resx.add')}</h3>
        <ResourceForm
          key={formKey}
          initial={{ branch_id: branchFilter, name: '', kind: 'room', device_type: null, is_active: true }}
          busy={create.isPending}
          deviceTypes={typeNames}
          onSave={(body) => create.mutate(body)}
        />
      </div>
      <p className="text-xs text-slate-500">{t('settings.deviceHint')}</p>
      <ErrorText error={create.error ?? save.error} />
    </div>
  )
}

// --- services -----------------------------------------------------------------------------------

function DevicePicker({
  value,
  onChange,
  types,
  className,
}: {
  value: string | null
  onChange: (v: string | null) => void
  types: { device_type: string; resources: number }[]
  className?: string
}) {
  const { t } = useTranslation()
  const known = types.some((d) => d.device_type === value)
  return (
    <Select value={value ?? ''} onChange={(e) => onChange(e.target.value || null)} className={className}>
      <option value="">{t('servx.noDevice')}</option>
      {value && !known && <option value={value}>{value}</option>}
      {types.map((d) => (
        <option key={d.device_type} value={d.device_type}>
          {deviceName(t, d.device_type)} ({t('servx.devices', { count: d.resources })})
        </option>
      ))}
    </Select>
  )
}

function ServiceRow({
  s,
  selected,
  onSelect,
  deviceTypes,
}: {
  s: ServiceItem
  selected: boolean
  onSelect: (on: boolean) => void
  deviceTypes: { device_type: string; resources: number }[]
}) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState(s)
  const save = useMutation({
    mutationFn: () =>
      updateService(s.id, {
        duration_min: form.duration_min,
        device_type: form.device_type || null,
        min_interval_days: form.min_interval_days || null,
        course_sessions: form.course_sessions || null,
        followup_call_days: form.followup_call_days ?? null,
        is_consultation: form.is_consultation,
        requires_consultation: form.requires_consultation,
        prep_uz: form.prep_uz || null,
        prep_ru: form.prep_ru || null,
      }),
    onSuccess: () => {
      setEditing(false)
      void queryClient.invalidateQueries({ queryKey: ['services'] })
      void queryClient.invalidateQueries({ queryKey: ['device-types'] })
    },
  })
  const num = (v: string) => (v === '' ? null : Number(v))
  const noDevice = s.device_type && !deviceTypes.find((d) => d.device_type === s.device_type)?.resources
  return (
    <>
      <tr className={`border-t border-slate-100 align-top ${selected ? 'bg-teal-50/50' : ''}`}>
        <td className="py-2 pr-2">
          <input
            type="checkbox"
            checked={selected}
            onChange={(e) => onSelect(e.target.checked)}
            aria-label={serviceName(s, i18n.language)}
          />
        </td>
        <td className="py-2 pr-3">
          {serviceName(s, i18n.language)}
          {s.is_consultation && (
            <span className="ml-2">
              <Badge>{t('servx.consultation')}</Badge>
            </span>
          )}
        </td>
        <td className="py-2 pr-3 whitespace-nowrap tabular-nums">{formatPrice(s.price)}</td>
        <td className="py-2 pr-3 whitespace-nowrap tabular-nums">
          {s.duration_min}′
          {!s.duration_confirmed && (
            <span className="ml-1" title={t('servx.durationMissingHint')}>
              <Badge tone="info">{t('servx.unset')}</Badge>
            </span>
          )}
        </td>
        <td className="py-2 pr-3 font-mono text-xs">
          {s.device_type ? deviceName(t, s.device_type) : '—'}
          {noDevice && <div className="font-sans text-amber-800">{t('servx.noSuchDevice')}</div>}
        </td>
        <td className="py-2 pr-3 tabular-nums">{s.min_interval_days ?? '—'}</td>
        <td className="py-2 text-right">
          <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setEditing(!editing)}>
            {t('settings.edit')}
          </Button>
        </td>
      </tr>
      {editing && (
        <tr>
          <td colSpan={7} className="pb-3">
            <div className="grid grid-cols-1 gap-3 rounded-md bg-slate-50 p-3 md:grid-cols-4">
              <Field label={t('settings.durationMin')}>
                <Input
                  type="number"
                  min={5}
                  max={600}
                  step={5}
                  value={form.duration_min}
                  onChange={(e) => setForm({ ...form, duration_min: Number(e.target.value) })}
                />
              </Field>
              <Field label={t('settings.requiredDevice')}>
                <DevicePicker
                  value={form.device_type}
                  onChange={(v) => setForm({ ...form, device_type: v })}
                  types={deviceTypes}
                />
              </Field>
              <Field label={t('settings.interval')}>
                <Input
                  type="number"
                  min={0}
                  value={form.min_interval_days ?? ''}
                  onChange={(e) => setForm({ ...form, min_interval_days: num(e.target.value) })}
                />
              </Field>
              <Field label={t('settings.sessions')}>
                <Input
                  type="number"
                  min={1}
                  value={form.course_sessions ?? ''}
                  onChange={(e) => setForm({ ...form, course_sessions: num(e.target.value) })}
                />
              </Field>
              <Field label={t('settings.followup')}>
                <Input
                  type="number"
                  min={0}
                  value={form.followup_call_days ?? ''}
                  onChange={(e) => setForm({ ...form, followup_call_days: num(e.target.value) })}
                />
              </Field>
              <div className="space-y-1 pt-6 text-sm">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={form.is_consultation}
                    onChange={(e) => setForm({ ...form, is_consultation: e.target.checked })}
                  />
                  {t('settings.consultation')}
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={form.requires_consultation}
                    onChange={(e) => setForm({ ...form, requires_consultation: e.target.checked })}
                  />
                  {t('settings.needsConsult')}
                </label>
              </div>
              <div className="md:col-span-2">
                <Field label={`${t('settings.prep')} (UZ)`}>
                  <Input
                    value={form.prep_uz ?? ''}
                    onChange={(e) => setForm({ ...form, prep_uz: e.target.value })}
                  />
                </Field>
                <Field label={`${t('settings.prep')} (RU)`}>
                  <Input
                    value={form.prep_ru ?? ''}
                    onChange={(e) => setForm({ ...form, prep_ru: e.target.value })}
                  />
                </Field>
              </div>
              <div className="flex items-end gap-2 md:col-span-4">
                <Button disabled={save.isPending || form.duration_min < 5} onClick={() => save.mutate()}>
                  {t('settings.save')}
                </Button>
                <Button variant="ghost" onClick={() => setEditing(false)}>
                  {t('patients.cancel')}
                </Button>
                <ErrorText error={save.error} />
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

function BulkBar({
  ids,
  onDone,
  deviceTypes,
}: {
  ids: string[]
  onDone: () => void
  deviceTypes: { device_type: string; resources: number }[]
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [duration, setDuration] = useState(30)
  const [device, setDevice] = useState<string | null>(null)
  const apply = useMutation({
    mutationFn: (body: Parameters<typeof bulkUpdateServices>[0]) => bulkUpdateServices(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['services'] })
      void queryClient.invalidateQueries({ queryKey: ['device-types'] })
      onDone()
    },
  })
  return (
    <div className="sticky top-0 z-10 flex flex-wrap items-end gap-3 rounded-md border border-teal-200 bg-teal-50 p-3 text-sm">
      <span className="self-center font-medium">{t('servx.selected', { count: ids.length })}</span>
      <div className="flex items-end gap-1">
        <Field label={t('settings.durationMin')}>
          <Input
            type="number"
            min={5}
            max={600}
            step={5}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
            className="w-24"
          />
        </Field>
        <Button
          disabled={apply.isPending || duration < 5}
          onClick={() => apply.mutate({ service_ids: ids, duration_min: duration })}
        >
          {t('servx.apply')}
        </Button>
      </div>
      <div className="flex items-end gap-1">
        <Field label={t('settings.requiredDevice')}>
          <DevicePicker value={device} onChange={setDevice} types={deviceTypes} className="w-56" />
        </Field>
        <Button
          variant="secondary"
          disabled={apply.isPending}
          onClick={() =>
            apply.mutate(
              device ? { service_ids: ids, device_type: device } : { service_ids: ids, clear_device: true },
            )
          }
        >
          {t('servx.apply')}
        </Button>
      </div>
      <Button variant="ghost" onClick={onDone}>
        {t('servx.clearSelection')}
      </Button>
      <div className="w-full empty:hidden">
        <ErrorText error={apply.error} />
      </div>
    </div>
  )
}

function ServicesTab() {
  const { t, i18n } = useTranslation()
  const [q, setQ] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [missing, setMissing] = useState(false)
  const [deviceFilter, setDeviceFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const { data: categories = [] } = useQuery({
    queryKey: ['service-categories'],
    queryFn: getServiceCategories,
    staleTime: 300_000,
  })
  const { data: deviceTypes = [] } = useQuery({ queryKey: ['device-types'], queryFn: getDeviceTypes })
  const { data, isPending, error } = useQuery({
    queryKey: ['services', 'settings', q, categoryId, missing, deviceFilter, offset],
    queryFn: () =>
      searchServices({
        q,
        offset,
        limit: 50,
        categoryId: categoryId || undefined,
        durationMissing: missing,
        deviceType: deviceFilter || undefined,
      }),
    placeholderData: keepPreviousData,
  })
  const filter =
    <T,>(set: (v: T) => void) =>
    (v: T) => {
      set(v)
      setOffset(0)
    }
  const pageIds = data?.items.map((s) => s.id) ?? []
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => selected.has(id))
  const select = (ids: string[], on: boolean) => {
    const next = new Set(selected)
    for (const id of ids) {
      if (on) next.add(id)
      else next.delete(id)
    }
    setSelected(next)
  }
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">{t('settings.siteNote')}</p>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_14rem_12rem_auto]">
        <Input
          type="search"
          placeholder={t('booking.searchService')}
          value={q}
          onChange={(e) => filter(setQ)(e.target.value)}
        />
        <Select
          value={categoryId}
          onChange={(e) => filter(setCategoryId)(e.target.value)}
          aria-label={t('servx.category')}
        >
          <option value="">{t('servx.allCategories')}</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {i18n.language === 'ru' ? c.name_ru : c.name_uz}
            </option>
          ))}
        </Select>
        <Select
          value={deviceFilter}
          onChange={(e) => filter(setDeviceFilter)(e.target.value)}
          aria-label={t('settings.requiredDevice')}
        >
          <option value="">{t('servx.anyDevice')}</option>
          {deviceTypes.map((d) => (
            <option key={d.device_type} value={d.device_type}>
              {deviceName(t, d.device_type)}
            </option>
          ))}
        </Select>
        <label className="flex items-center gap-2 text-sm whitespace-nowrap">
          <input type="checkbox" checked={missing} onChange={(e) => filter(setMissing)(e.target.checked)} />
          {t('servx.durationMissing')}
        </label>
      </div>
      {selected.size > 0 && (
        <BulkBar ids={[...selected]} deviceTypes={deviceTypes} onDone={() => setSelected(new Set())} />
      )}
      <ErrorText error={error} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] text-left text-sm">
          <thead className="text-xs text-slate-500 uppercase">
            <tr>
              <th className="w-8 pb-2">
                <input
                  type="checkbox"
                  checked={allOnPage}
                  onChange={(e) => select(pageIds, e.target.checked)}
                  aria-label={t('servx.selectPage')}
                />
              </th>
              <th className="pb-2">{t('settings.name')}</th>
              <th className="pb-2">{t('settings.price')}</th>
              <th className="pb-2">{t('settings.durationMin')}</th>
              <th className="pb-2">{t('settings.requiredDevice')}</th>
              <th className="pb-2">{t('settings.interval')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data?.items.map((s) => (
              <ServiceRow
                key={`${s.id}-${s.duration_min}-${s.device_type}`}
                s={s}
                selected={selected.has(s.id)}
                onSelect={(on) => select([s.id], on)}
                deviceTypes={deviceTypes}
              />
            ))}
          </tbody>
        </table>
      </div>
      {isPending && <p className="text-sm text-slate-500">{t('app.loading')}</p>}
      {data && data.items.length === 0 && (
        <p className="py-4 text-center text-sm text-slate-500">
          {missing ? t('servx.allSet') : t('servx.nothingFound')}
        </p>
      )}
      {data && data.total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600">
          <span>{t('patients.total', { count: data.total })}</span>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              {t('audit.prev')}
            </Button>
            <Button
              variant="secondary"
              disabled={offset + 50 >= data.total}
              onClick={() => setOffset(offset + 50)}
            >
              {t('audit.next')}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function SettingsPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const isAdmin = user?.role === 'admin'
  const canPlan = isAdmin || user?.role === 'supervisor'
  const tabs: readonly Tab[] = isAdmin ? TABS : (['doctors', 'scripts', 'templates'] as const)
  const tab = tabs.find((k) => k === params.get('tab')) ?? 'doctors'
  return (
    <div className="max-w-6xl space-y-4">
      <h1 className="text-2xl font-semibold">{t('settings.title')}</h1>
      <SyncInfo isAdmin={isAdmin} />
      <div className="flex gap-1 overflow-x-auto overflow-y-hidden border-b border-slate-200 whitespace-nowrap">
        {tabs.map((k) => (
          <button
            key={k}
            onClick={() => setParams({ tab: k })}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === k ? 'border-teal-700 font-medium text-teal-800' : 'border-transparent text-slate-600'}`}
          >
            {k === 'scripts'
              ? t('scripts.title')
              : k === 'templates'
                ? t('templates.title')
                : t(`settings.${k}`)}
          </button>
        ))}
      </div>
      <Card>
        {tab === 'doctors' && <DoctorsTab isAdmin={isAdmin} canPlan={canPlan} />}
        {tab === 'resources' && <ResourcesTab />}
        {tab === 'services' && <ServicesTab />}
        {tab === 'scripts' && <ScriptsEditor />}
        {tab === 'templates' && <TemplatesEditor />}
      </Card>
    </div>
  )
}
