/**
 * The camera, shared by the kassa and the bar (B-05 SD17; AC14, AC42; B-06
 * SD12): the rear camera into a `<video>`, a frame sampled about every 200 ms
 * and decoded, and on a token every track stopped before `onToken`. Permission
 * denied (or no camera) says so; the code field stays where it is.
 */
import { useEffect, useRef, useState } from 'react'
import { Button } from '../ui/Button'
import { decode } from './decodeQr'
import styles from './Scanner.module.css'

export const SAMPLE_MS = 200

export function Scanner({
  onToken,
  onClose,
}: {
  onToken: (token: string) => void
  onClose: () => void
}) {
  const video = useRef<HTMLVideoElement>(null)
  const [error, setError] = useState<string | null>(null)
  const latest = useRef(onToken)
  useEffect(() => {
    latest.current = onToken
  })

  useEffect(() => {
    let stream: MediaStream | null = null
    let timer: ReturnType<typeof setInterval> | null = null
    let done = false
    let decoding = false
    const canvas = document.createElement('canvas')

    const stop = () => {
      done = true
      if (timer !== null) clearInterval(timer)
      stream?.getTracks().forEach((track) => track.stop())
    }

    const sample = async () => {
      const playing = video.current
      if (done || decoding || playing === null || playing.videoWidth === 0) return
      canvas.width = playing.videoWidth
      canvas.height = playing.videoHeight
      const context = canvas.getContext('2d', { willReadFrequently: true })
      if (context === null) return
      context.drawImage(playing, 0, 0)
      decoding = true
      try {
        const token = await decode(context.getImageData(0, 0, canvas.width, canvas.height))
        if (token !== null && !done) {
          stop()
          latest.current(token)
        }
      } finally {
        decoding = false
      }
    }

    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } }).then(
      (opened) => {
        stream = opened
        if (done) {
          stop()
          return
        }
        if (video.current !== null) {
          video.current.srcObject = opened
          void video.current.play().catch(() => {})
        }
        timer = setInterval(() => void sample(), SAMPLE_MS)
      },
      () => setError('Geen toegang tot de camera.'),
    )
    return stop
  }, [])

  return (
    <section className={styles.scanner} aria-label="Camera">
      {error === null ? (
        <video ref={video} className={styles.video} muted playsInline />
      ) : (
        <div className={styles.err} role="alert">
          {error}
        </div>
      )}
      <Button onClick={onClose}>Annuleren</Button>
    </section>
  )
}
