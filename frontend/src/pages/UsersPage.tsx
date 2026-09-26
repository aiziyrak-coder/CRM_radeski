import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge, Button, Card, ErrorText, Field, Input, Notice, Select } from '../components/ui'
import { api, type Language, type Role, type User } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import { ROLES } from '../lib/navigation'
import { formatDateTime } from '../lib/patients'

type Draft = { username: string; full_name: string; role: Role; language: Language; password: string }
const EMPTY: Draft = { username: '', full_name: '', role: 'operator', language: 'uz', password: '' }

function CreateUserForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Draft>(EMPTY)
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

function UserRow({ user, isSelf, extensions }: { user: User; isSelf: boolean; extensions: string[] }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [resetting, setResetting] = useState(false)
  const [newPassword, setNewPassword] = useState('')

  const update = useMutation({
    mutationFn: (body: Partial<Pick<User, 'role' | 'is_active' | 'sip_extension'>>) =>
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
          <td colSpan={5} className="pb-3">
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
  const { t } = useTranslation()
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
        <ErrorText error={error} />
        {isPending ? null : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="text-xs text-slate-500 uppercase">
                <tr>
                  <th className="pb-2 font-medium">{t('users.fullName')}</th>
                  <th className="pb-2 font-medium">{t('users.role')}</th>
                  <th className="pb-2 font-medium">{t('users.status')}</th>
                  <th className="pb-2 font-medium">{t('users.lastLogin')}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {users?.map((u) => (
                  <UserRow key={u.id} user={u} isSelf={u.id === me?.id} extensions={extensions} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
