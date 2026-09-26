import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Card, ErrorText, Field, Input, Notice } from '../components/ui'
import { api, setAccessToken, type TokenResponse } from '../lib/api'
import { useAuth } from '../lib/auth-context'

export default function ProfilePage() {
  const { t } = useTranslation()
  const { user, setUser } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')

  const change = useMutation({
    mutationFn: () =>
      api<TokenResponse>('/auth/change-password', {
        method: 'POST',
        body: { current_password: current, new_password: next },
      }),
    onSuccess: (tok) => {
      setAccessToken(tok.access_token)
      setUser(tok.user)
      setCurrent('')
      setNext('')
    },
  })

  if (!user) return null
  const submit = (e: FormEvent) => {
    e.preventDefault()
    change.mutate()
  }

  return (
    <div className="max-w-xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{t('profile.title')}</h1>
        <p className="mt-1 text-slate-600">
          {user.full_name} · {user.username} · {t(`roles.${user.role}`)}
        </p>
      </div>
      <Card title={t('profile.changePassword')}>
        <form onSubmit={submit} className="space-y-4">
          <Field label={t('profile.currentPassword')}>
            <Input
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              required
            />
          </Field>
          <Field label={t('profile.newPassword')}>
            <Input
              type="password"
              autoComplete="new-password"
              minLength={8}
              value={next}
              onChange={(e) => setNext(e.target.value)}
              required
            />
          </Field>
          <ErrorText error={change.error} />
          {change.isSuccess && <Notice>{t('profile.changed')}</Notice>}
          <Button type="submit" disabled={change.isPending}>
            {t('users.save')}
          </Button>
        </form>
      </Card>
    </div>
  )
}
