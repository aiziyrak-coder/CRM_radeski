import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation } from 'react-router'
import { Button, ErrorText, Field, Input } from '../components/ui'
import type { Language, TotpChallenge } from '../lib/api'
import { useAuth } from '../lib/auth-context'

export default function LoginPage() {
  const { t, i18n } = useTranslation()
  const { status, login, verifyTotp, logoutReason } = useAuth()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [challenge, setChallenge] = useState<TotpChallenge | null>(null)
  const [code, setCode] = useState('')

  if (status === 'authenticated') {
    const from = (location.state as { from?: string } | null)?.from ?? '/'
    return <Navigate to={from} replace />
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (challenge) {
        await verifyTotp(challenge.challenge, code.trim())
      } else {
        setChallenge(await login(username.trim(), password))
        setPassword('')
      }
    } catch (err) {
      setError(err)
      setPassword('')
      setCode('')
      // an expired challenge means starting over from the password
      if ((err as { code?: string }).code === 'challenge_expired') setChallenge(null)
    } finally {
      setBusy(false)
    }
  }

  const otherLang: Language = i18n.language === 'uz' ? 'ru' : 'uz'

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <div className="text-2xl font-semibold text-teal-800">{t('app.title')}</div>
          <div className="text-sm text-slate-500">{t('app.clinic')}</div>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-lg border border-slate-200 bg-white p-6">
          <h1 className="text-lg font-semibold">{t('auth.title')}</h1>
          {logoutReason && logoutReason !== 'manual' && (
            <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {t(`auth.${logoutReason}`)}
            </p>
          )}
          {challenge ? (
            <>
              {challenge.setup ? (
                <div className="space-y-2 text-sm text-slate-700">
                  <p>{t('auth.totpSetup')}</p>
                  {challenge.qr && <img src={challenge.qr} alt="QR" className="mx-auto h-44 w-44" />}
                  <p className="text-xs text-slate-500">
                    {t('auth.totpSecret')}: <span className="font-mono break-all">{challenge.secret}</span>
                  </p>
                </div>
              ) : (
                <p className="text-sm text-slate-700">{t('auth.totpPrompt')}</p>
              )}
              <Field label={t('auth.totpCode')}>
                <Input
                  autoFocus
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                  required
                />
              </Field>
            </>
          ) : (
            <>
              <Field label={t('auth.username')}>
                <Input
                  autoFocus
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                />
              </Field>
              <Field label={t('auth.password')}>
                <Input
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </Field>
            </>
          )}
          <ErrorText error={error} />
          <Button type="submit" className="w-full" disabled={busy}>
            {t('auth.submit')}
          </Button>
        </form>
        <div className="mt-4 text-center">
          <Button variant="ghost" onClick={() => void i18n.changeLanguage(otherLang)}>
            {t(`lang.${otherLang}`)}
          </Button>
        </div>
      </div>
    </div>
  )
}
