import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { recordingUrl } from '../lib/telephony'
import { Button } from './ui'

/** Loads the recording only when asked (they are a few hundred KB each). */
export default function RecordingPlayer({ callId }: { callId: string }) {
  const { t } = useTranslation()
  const [url, setUrl] = useState<string | null>(null)
  const [state, setState] = useState<'idle' | 'loading' | 'error'>('idle')
  useEffect(() => () => void (url && URL.revokeObjectURL(url)), [url])

  if (url) return <audio src={url} controls autoPlay className="h-8 w-64 max-w-full" />
  return (
    <Button
      variant="secondary"
      className="px-2 py-1 text-xs"
      disabled={state === 'loading'}
      onClick={() => {
        setState('loading')
        recordingUrl(callId).then(setUrl, () => setState('error'))
      }}
    >
      {state === 'error' ? t('calls.noRecording') : t('calls.listen')}
    </Button>
  )
}
