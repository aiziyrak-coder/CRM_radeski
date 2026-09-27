import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatAt } from '../lib/ai'
import { recordingUrl } from '../lib/telephony'
import { Button } from './ui'

/**
 * Loads the recording only when asked (they are a few hundred KB each). With `at` the button
 * reads "▶ 1:23" and playback starts a second before that moment (a QA violation, a red flag).
 */
export default function RecordingPlayer({ callId, at }: { callId: string; at?: number | null }) {
  const { t } = useTranslation()
  const audio = useRef<HTMLAudioElement | null>(null)
  const [url, setUrl] = useState<string | null>(null)
  const [state, setState] = useState<'idle' | 'loading' | 'error'>('idle')
  useEffect(() => () => void (url && URL.revokeObjectURL(url)), [url])
  const start = at != null ? Math.max(0, at - 1) : 0

  if (url) {
    return (
      <audio
        ref={audio}
        src={url}
        controls
        autoPlay
        className="h-8 w-64 max-w-full"
        onLoadedMetadata={() => {
          if (audio.current && start) audio.current.currentTime = start
        }}
      />
    )
  }
  return (
    <Button
      variant="secondary"
      className="px-2 py-1 text-xs"
      disabled={state === 'loading'}
      aria-label={at != null ? t('calls.listenAt', { at: formatAt(at) }) : undefined}
      onClick={() => {
        setState('loading')
        recordingUrl(callId).then(setUrl, () => setState('error'))
      }}
    >
      {state === 'error' ? t('calls.noRecording') : at != null ? `▶ ${formatAt(at)}` : t('calls.listen')}
    </Button>
  )
}
