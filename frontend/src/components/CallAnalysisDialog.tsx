import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatAt, getCallAnalysis, markFlagsReviewed, type CallAnalysis } from '../lib/ai'
import { getScripts } from '../lib/ops'
import { recordingUrl } from '../lib/telephony'
import { Badge, Button, ErrorText, Modal } from './ui'

export function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) return <span className="text-slate-400">—</span>
  const tone = score >= 80 ? 'good' : score >= 60 ? 'info' : 'bad'
  return <Badge tone={tone}>{score}</Badge>
}

/** Audio that can jump to a moment of the call (violations, transcript lines). */
function useSeekableRecording(callId: string) {
  const audio = useRef<HTMLAudioElement | null>(null)
  const pending = useRef<number | null>(null)
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => () => void (url && URL.revokeObjectURL(url)), [url])
  const seek = (at: number | null) => {
    const t = Math.max(0, (at ?? 0) - 1) // start a second early so the quote isn't cut
    if (audio.current && url) {
      audio.current.currentTime = t
      void audio.current.play()
      return
    }
    pending.current = t
    recordingUrl(callId).then(setUrl, () => setError(true))
  }
  const player = url ? (
    <audio
      ref={audio}
      src={url}
      controls
      className="h-9 w-full"
      onLoadedMetadata={() => {
        if (audio.current && pending.current !== null) {
          audio.current.currentTime = pending.current
          pending.current = null
          void audio.current.play()
        }
      }}
    />
  ) : null
  return { seek, player, error }
}

/** Why an analysis was skipped or failed: the worker stores a code or a raw exception message. */
function errorKey(error: string): string {
  if (error === 'too_short' || error === 'no_speech') return error
  if (/budget/i.test(error)) return 'budget'
  if (/OPENAI_API_KEY/.test(error)) return 'disabled'
  return 'generic'
}

function At({ at, onSeek }: { at: number | null; onSeek: (at: number | null) => void }) {
  if (at === null) return null
  return (
    <button onClick={() => onSeek(at)} className="font-mono text-xs text-teal-800 hover:underline">
      ▶ {formatAt(at)}
    </button>
  )
}

function Body({ a, canAck }: { a: CallAnalysis; canAck: boolean }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const { seek, player, error } = useSeekableRecording(a.call_id)
  const ack = useMutation({
    mutationFn: () => markFlagsReviewed(a.call_id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['ai'] }),
  })
  const { data: scripts = [] } = useQuery({
    queryKey: ['scripts'],
    queryFn: () => getScripts(),
    staleTime: 600_000,
    enabled: Boolean(a.conversation_type),
  })
  if (a.status !== 'ready') {
    return (
      <p className="text-sm text-slate-600">
        {t(`ai.status.${a.status}`)}
        {a.error && (
          <span className="block text-xs text-red-700" title={a.error}>
            {t(`ai.errors.${errorKey(a.error)}`)}
          </span>
        )}
      </p>
    )
  }
  const lang = i18n.language === 'ru' ? 'ru' : 'uz'
  const conversation =
    scripts.find((s) => s.code === a.conversation_type && s.language === lang) ??
    scripts.find((s) => s.code === a.conversation_type)
  const criterionName = (code: string) => t(`ai.criteria.${code}`, { defaultValue: code })
  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-3xl font-semibold tabular-nums">{a.score ?? '—'}</span>
        <span className="text-slate-500">/ 100</span>
        {a.conversation_type && <Badge tone="info">{conversation?.title ?? a.conversation_type}</Badge>}
        {a.suggested_outcome && <Badge>{t(`outcomes.${a.suggested_outcome}`)}</Badge>}
        {a.review && <Badge tone="good">{t(`ai.review.${a.review}`)}</Badge>}
      </div>
      <p className="text-slate-800">{a.summary}</p>
      <div>
        {player ?? (
          <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => seek(0)}>
            {t('calls.listen')}
          </Button>
        )}
        {error && <p className="text-xs text-red-700">{t('calls.noRecording')}</p>}
      </div>

      {(a.red_flags?.length ?? 0) > 0 && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3">
          <div className="mb-1 flex items-center justify-between">
            <h3 className="font-medium text-red-800">{t('ai.redFlags')}</h3>
            {canAck && !a.flags_reviewed_at && (
              <Button
                variant="secondary"
                className="px-2 py-1 text-xs"
                disabled={ack.isPending}
                onClick={() => ack.mutate()}
              >
                {t('ai.markReviewed')}
              </Button>
            )}
            {a.flags_reviewed_at && <span className="text-xs text-slate-500">{t('ai.reviewed')}</span>}
          </div>
          <ErrorText error={ack.error} />
          <ul className="space-y-1">
            {a.red_flags!.map((f, i) => (
              <li key={i}>
                <span className="font-medium">{t(`ai.flags.${f.code}`)}</span>: «{f.quote}»{' '}
                <At at={f.at} onSeek={seek} />
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h3 className="mb-1 font-medium">{t('ai.criteriaTitle')}</h3>
        <ul className="space-y-1">
          {a.criteria?.map((c) => (
            <li key={c.code} className="flex gap-2">
              <span
                className={
                  c.passed === null ? 'text-slate-400' : c.passed ? 'text-emerald-700' : 'text-red-700'
                }
              >
                {c.passed === null ? '—' : c.passed ? '✓' : '✗'}
              </span>
              <span>
                {criterionName(c.code)}
                {c.comment && <span className="text-slate-500"> — {c.comment}</span>}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {(a.violations?.length ?? 0) > 0 && (
        <div>
          <h3 className="mb-1 font-medium">{t('ai.violations')}</h3>
          <ul className="space-y-1">
            {a.violations!.map((v, i) => (
              <li key={i}>
                <span className="text-slate-600">{criterionName(v.criterion)}:</span> «{v.quote}»{' '}
                <At at={v.at} onSeek={seek} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {a.extracted && (
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">
          {(['interest', 'preferred_time', 'source', 'next_step'] as const).map(
            (k) =>
              a.extracted![k] && (
                <div key={k}>
                  <dt className="text-xs text-slate-500">{t(`ai.extracted.${k}`)}</dt>
                  <dd>{a.extracted![k]}</dd>
                </div>
              ),
          )}
        </dl>
      )}
      {((a.questions?.length ?? 0) > 0 || (a.objections?.length ?? 0) > 0) && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {(['questions', 'objections'] as const).map(
            (k) =>
              (a[k]?.length ?? 0) > 0 && (
                <div key={k}>
                  <h3 className="mb-1 font-medium">{t(`ai.${k}`)}</h3>
                  <ul className="list-disc pl-5">
                    {a[k]!.map((q, i) => (
                      <li key={i}>{q}</li>
                    ))}
                  </ul>
                </div>
              ),
          )}
        </div>
      )}

      <details>
        <summary className="cursor-pointer font-medium">{t('ai.transcript')}</summary>
        <div className="mt-2 max-h-80 space-y-1 overflow-y-auto rounded-md bg-slate-50 p-2">
          {a.transcript?.map((s, i) => (
            <div key={i} className={s.ch === 'operator' ? 'pr-8' : 'pl-8 text-right'}>
              <At at={s.start} onSeek={seek} />{' '}
              <span className={s.ch === 'operator' ? 'text-teal-900' : 'text-slate-800'}>
                <b>{t(s.ch === 'operator' ? 'ai.operator' : 'ai.patient')}:</b> {s.text}
              </span>
            </div>
          ))}
        </div>
      </details>
      <p className="text-xs text-slate-400">
        {a.stt_model} · {a.llm_model} · {a.prompt_version} · {i18n.language}
      </p>
    </div>
  )
}

export default function CallAnalysisDialog({
  callId,
  onClose,
  canAck = false,
}: {
  callId: string
  onClose: () => void
  canAck?: boolean
}) {
  const { t } = useTranslation()
  const { data, error } = useQuery({
    queryKey: ['ai', 'call', callId],
    queryFn: () => getCallAnalysis(callId),
  })
  return (
    <Modal title={t('ai.analysisTitle')} onClose={onClose} wide>
      <ErrorText error={error} />
      {data && <Body a={data} canAck={canAck} />}
    </Modal>
  )
}
