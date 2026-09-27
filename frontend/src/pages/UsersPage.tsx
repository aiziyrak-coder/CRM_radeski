import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Badge, Button, Card, ErrorText, Field, Input, Notice, Select } from '../components/ui'
import { api, type Language, type Role, type User } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import { ROLES } from '../lib/navigation'
import { formatDateTime } from '../lib/patients'
import { branchName, doctorName, getBranches, getDoctors, type Branch, type Doctor } from '../lib/scheduling'

type Draft = {
  username: string
  full_name: string
  role: Role
  language: Language
  password: string
  branch_id: string | null
}
const EMPTY: Draft = {
  username: '',
  full_name: '',
  role: 'operator',
  language: 'uz',
  password: '',
  branch_id: null,
}
/** roles that work at one branch: their screens open on it */
const BRANCH_ROLES: Role[] = ['registrar', 'doctor']

function useBranches() {
  return useQuery({ queryKey: ['branches'], queryFn: getBranches, staleTime: 300_000 }).data ?? []
}

function BranchSelect({
  value,
  onChange,
  branches,
  disabled,
  className,
}: {
  value: string | null
  onChange: (v: string | null) => void
  branches: Branch[]
  disabled?: boolean
  className?: string
}) {
  const { t, i18n } = useTranslation()
  return (
    <Select
      value={value ?? ''}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value || null)}
      className={className}
      aria-label={t('schedule.branch')}
    >
      <option value="">{t('usersx.noBranch')}</option>
      {branches.map((b) => (
        <option key={b.id} value={b.id}>
          {branchName(b, i18n.language)}
          {b.is_active ? '' : ` (${t('settings.inactive')})`}
        </option>
      ))}
    </Select>
  )
}

function CreateUserForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const branches = useBranches()
  const create = useMutation({
    mutationFn: (body: Draft) => api<User>('/users', { method: 'POST', body }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['users'] })
      onDone()
    },
  })
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => ({ ...d, [k]: v }))

  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate({ ...draft, username: draft.username.trim().toLowerCase() })
  }

  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <Field label={t('users.fullName')}>
        <Input
          value={draft.full_name}
          onChange={(e) => set('full_name', e.target.value)}
          required
          minLength={2}
        />
      </Field>
      <Field label={t('users.username')} hint={t('users.usernameHint')}>
        <Input
          value={draft.username}
          onChange={(e) => set('username', e.target.value)}
          pattern="[a-zA-Z0-9._\-]{3,64}"
          autoComplete="off"
          required
        />
      </Field>
      <Field label={t('users.role')}>
        <Select value={draft.role} onChange={(e) => set('role', e.target.value as Role)}>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {t(`roles.${r}`)}
            </option>
          ))}
        </Select>
      </Field>
      <Field
        label={t('schedule.branch')}
        hint={BRANCH_ROLES.includes(draft.role) ? t('usersx.branchHint') : undefined}
      >
        <BranchSelect value={draft.branch_id} onChange={(v) => set('branch_id', v)} branches={branches} />
      </Field>
      <Field label={t('users.language')}>
        <Select value={draft.language} onChange={(e) => set('language', e.target.value as Language)}>
          <option value="uz">{t('lang.uz')}</option>
          <option value="ru">{t('lang.ru')}</option>
        </Select>
      </Field>
      <Field label={t('users.password')}>
        <Input
          type="password"
          autoComplete="new-password"
          value={draft.password}
          onChange={(e) => set('password', e.target.value)}
          minLength={8}
          required
        />
      </Field>
      <div className="flex items-end gap-2">
        <Button type="submit" disabled={create.isPending}>
          {t('users.save')}
        </Button>
        <Button variant="secondary" onClick={onDone}>
          {t('users.cancel')}
        </Button>
      </div>
      <div className="md:col-span-2">
        <ErrorText error={create.error} />
      </div>
    </form>
  )
}

const CALL_CENTER: Role[] = ['operator', 'supervisor', 'admin']

function UserRow({
  user,
  isSelf,
  extensions,
  branches,
  doctor,
}: {
  user: User
  isSelf: boolean
  extensions: string[]
  branches: Branch[]
  /** the doctor card this login is linked to (doctor role) */
  doctor: Doctor | undefined
}) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [resetting, setResetting] = useState(false)
  const [newPassword, setNewPassword] = useState('')

  const update = useMutation({
    mutationFn: (body: Partial<Pick<User, 'role' | 'is_active' | 'sip_extension' | 'branch_id'>>) =>
      api<User>(`/users/${user.id}`, { method: 'PATCH', body }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['users'] }),
  })
  const resetTotp = useMutation({
    mutationFn: () => api<void>(`/users/${user.id}/totp-reset`, { method: 'POST' }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['users'] }),
  })
  const reset = useMutation({
    mutationFn: (password: string) =>
      api<void>(`/users/${user.id}/password`, { method: 'POST', body: { password } }),
    onSuccess: () => {
      setResetting(false)
      setNewPassword('')
    },
  })

  return (
    <>
      <tr className="border-t border-slate-100 align-top">
        <td className="py-3 pr-4">
          <div className="font-medium">{user.full_name}</div>
          <div className="text-xs text-slate-500">{user.username}</div>
        </td>
        <td className="py-3 pr-4">
          <Select
            value={user.role}
            disabled={isSelf || update.isPending}
            onChange={(e) => update.mutate({ role: e.target.value as Role })}
            className="max-w-52"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {t(`roles.${r}`)}
              </option>
            ))}
          </Select>
          {CALL_CENTER.includes(user.role) && extensions.length > 0 && (
            <label className="mt-2 flex items-center gap-2 text-xs whitespace-nowrap text-slate-600">
              {t('users.extension')}
              <Select
                value={user.sip_extension ?? ''}
                disabled={update.isPending}
                onChange={(e) => update.mutate({ sip_extension: e.target.value || null })}
                className="w-24 py-1 text-xs"
              >
                <option value="">—</option>
                {extensions.map((x) => (
                  <option key={x} value={x}>
                    {x}
                  </option>
                ))}
              </Select>
            </label>
          )}
        </td>
        <td className="py-3 pr-4">
          <BranchSelect
            value={user.branch_id}
            onChange={(v) => update.mutate({ branch_id: v })}
            branches={branches}
            disabled={update.isPending}
            className="max-w-48"
          />
          {BRANCH_ROLES.includes(user.role) && !user.branch_id && (
            <p className="mt-1 text-xs text-amber-800">{t('usersx.branchMissing')}</p>
          )}
          {user.role === 'doctor' && (
            <p className="mt-1 text-xs">
              {doctor ? (
                <span className="text-slate-600">
                  {t('usersx.doctorCard')}: {doctorName(doctor, i18n.language)}
                </span>
              ) : (
                <Link to="/settings" className="text-amber-800 hover:underline">
                  {t('usersx.doctorNotLinked')}
                </Link>
              )}
            </p>
          )}
        </td>
        <td className="py-3 pr-4">
          <Badge tone={user.is_active ? 'good' : 'neutral'}>
            {user.is_active ? t('users.active') : t('users.inactive')}
          </Badge>
          {(user.role === 'admin' || user.role === 'owner') && (
            <div className="mt-1">
              <Badge tone={user.totp_enabled ? 'good' : 'neutral'}>
                {user.totp_enabled ? t('users.totpOn') : t('users.totpOff')}
              </Badge>
              {user.totp_enabled && !isSelf && (
                <button
                  className="ml-2 text-xs text-teal-800 hover:underline"
                  disabled={resetTotp.isPending}
                  onClick={() => window.confirm(t('users.totpResetConfirm')) && resetTotp.mutate()}
                >
                  {t('users.totpReset')}
                </button>
              )}
            </div>
          )}
        </td>
        <td className="py-3 pr-4 text-sm text-slate-600">
          {user.last_login_at ? formatDateTime(user.last_login_at) : t('users.never')}
        </td>
        <td className="py-3 text-right whitespace-nowrap">
          <Button variant="ghost" onClick={() => setResetting((v) => !v)}>
            {t('users.resetPassword')}
          </Button>
          {!isSelf && (
            <Button
              variant={user.is_active ? 'danger' : 'secondary'}
              disabled={update.isPending}
              onClick={() => update.mutate({ is_active: !user.is_active })}
            >
              {user.is_active ? t('users.deactivate') : t('users.activate')}
            </Button>
          )}
        </td>
      </tr>
      {(resetting || update.error || resetTotp.error || reset.isSuccess) && (
        <tr>
          <td colSpan={6} className="pb-3">
            {resetting && (
              <form
                className="flex max-w-md items-end gap-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  reset.mutate(newPassword)
                }}
              >
                <Field label={t('users.newPassword')}>
                  <Input
                    type="password"
                    autoComplete="new-password"
                    minLength={8}
                    required
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                  />
                </Field>
                <Button type="submit" disabled={reset.isPending}>
                  {t('users.save')}
                </Button>
              </form>
            )}
            <ErrorText error={update.error ?? reset.error ?? resetTotp.error} />
            {reset.isSuccess && !resetting && <Notice>{t('users.passwordReset')}</Notice>}
          </td>
        </tr>
      )}
    </>
  )
}

export default function UsersPage() {
  const { t, i18n } = useTranslation()
  const { user: me } = useAuth()
  const [adding, setAdding] = useState(false)
  const {
    data: users,
    error,
    isPending,
  } = useQuery({
    queryKey: ['users'],
    queryFn: () => api<User[]>('/users'),
  })
  const { data: extensions = [] } = useQuery({
    queryKey: ['telephony', 'extensions'],
    queryFn: () => api<string[]>('/telephony/extensions'),
    staleTime: Infinity,
  })
  const branches = useBranches()
  const { data: doctors = [] } = useQuery({ queryKey: ['doctors', 'all'], queryFn: () => getDoctors(false) })
  const [q, setQ] = useState('')
  const [role, setRole] = useState<Role | ''>('')
  const [branchFilter, setBranchFilter] = useState('')
  const needle = q.trim().toLowerCase()
  const shown = (users ?? []).filter(
    (u) =>
      (!role || u.role === role) &&
      (!branchFilter || (branchFilter === 'none' ? !u.branch_id : u.branch_id === branchFilter)) &&
      (!needle || u.full_name.toLowerCase().includes(needle) || u.username.includes(needle)),
  )

  return (
    <div className="max-w-6xl space-y-6">
      <h1 className="text-2xl font-semibold">{t('users.title')}</h1>
      {adding ? (
        <Card title={t('users.add')}>
          <CreateUserForm onDone={() => setAdding(false)} />
        </Card>
      ) : (
        <Button onClick={() => setAdding(true)}>{t('users.add')}</Button>
      )}
      <Card>
        <div className="mb-4 flex flex-wrap gap-2">
          <Input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t('usersx.search')}
            className="min-w-0 flex-1 sm:w-64 sm:flex-none"
          />
          <Select
            value={role}
            onChange={(e) => setRole(e.target.value as Role | '')}
            className="min-w-0 flex-1 sm:w-48 sm:flex-none"
            aria-label={t('users.role')}
          >
            <option value="">{t('usersx.allRoles')}</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {t(`roles.${r}`)}
              </option>
            ))}
          </Select>
          <Select
            value={branchFilter}
            onChange={(e) => setBranchFilter(e.target.value)}
            className="min-w-0 flex-1 sm:w-48 sm:flex-none"
            aria-label={t('schedule.branch')}
          >
            <option value="">{t('usersx.allBranches')}</option>
            <option value="none">{t('usersx.noBranch')}</option>
            {branches.map((b) => (
              <option key={b.id} value={b.id}>
                {branchName(b, i18n.language)}
              </option>
            ))}
          </Select>
        </div>
        <ErrorText error={error} />
        {isPending ? (
          <p className="text-sm text-slate-500">{t('app.loading')}</p>
        ) : shown.length === 0 ? (
          <p className="py-4 text-center text-sm text-slate-500">{t('usersx.none')}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead className="text-xs text-slate-500 uppercase">
                <tr>
                  <th className="pb-2 font-medium">{t('users.fullName')}</th>
                  <th className="pb-2 font-medium">{t('users.role')}</th>
                  <th className="pb-2 font-medium">{t('schedule.branch')}</th>
                  <th className="pb-2 font-medium">{t('users.status')}</th>
                  <th className="pb-2 font-medium">{t('users.lastLogin')}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {shown.map((u) => (
                  <UserRow
                    key={u.id}
                    user={u}
                    isSelf={u.id === me?.id}
                    extensions={extensions}
                    branches={branches}
                    doctor={doctors.find((d) => d.user_id === u.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
