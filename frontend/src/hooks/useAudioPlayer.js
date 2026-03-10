/**
 * useAudioPlayer — Web Audio API playback queue for avatar TTS audio.
 *
 * Receives base64-encoded WAV chunks from the WebSocket and assembles
 * them into AudioBuffers, then plays them through the AudioContext.
 *
 * Usage:
 *   const { handleWsMessage, speaking, cancelAll } = useAudioPlayer()
 *
 * Feed every incoming WebSocket message into handleWsMessage().
 * The hook manages buffering, decoding, and serialised playback.
 */

import { useRef, useState, useCallback, useEffect } from 'react'

export function useAudioPlayer() {
  const ctxRef = useRef(null)          // AudioContext (created on first user interaction)
  const bufferMapRef = useRef({})      // avatar_id → accumulated base64 chunks
  const queueRef = useRef([])          // [{avatarId, audioBuffer, utteranceType}]
  const playingRef = useRef(false)
  const sourceRef = useRef(null)       // current AudioBufferSourceNode
  const [speaking, setSpeaking] = useState(null) // {avatarId, avatarName, utteranceType} | null

  // Lazily create AudioContext (requires user gesture)
  const getCtx = useCallback(() => {
    if (!ctxRef.current) {
      ctxRef.current = new (window.AudioContext || window.webkitAudioContext)()
    }
    return ctxRef.current
  }, [])

  const cancelAll = useCallback(() => {
    queueRef.current = []
    if (sourceRef.current) {
      try { sourceRef.current.stop() } catch {}
      sourceRef.current = null
    }
    setSpeaking(null)
    playingRef.current = false
  }, [])

  const playNext = useCallback(async () => {
    if (playingRef.current || queueRef.current.length === 0) return
    const job = queueRef.current.shift()
    playingRef.current = true
    setSpeaking({ avatarId: job.avatarId, avatarName: job.avatarName, utteranceType: job.utteranceType })

    const ctx = getCtx()
    // Resume context if suspended (browser autoplay policy)
    if (ctx.state === 'suspended') await ctx.resume()

    const source = ctx.createBufferSource()
    sourceRef.current = source

    // Apply volume for backchannels
    const gainNode = ctx.createGain()
    gainNode.gain.value = job.utteranceType === 'backchannel' ? 0.6 : 1.0
    source.connect(gainNode)
    gainNode.connect(ctx.destination)

    source.buffer = job.audioBuffer
    source.onended = () => {
      sourceRef.current = null
      playingRef.current = false
      setSpeaking(null)
      // Play next in queue
      playNext()
    }
    source.start()
  }, [getCtx])

  const handleWsMessage = useCallback(async (msg) => {
    if (!msg || !msg.type) return

    switch (msg.type) {
      case 'audio_start': {
        // Initialise accumulation buffer for this avatar
        bufferMapRef.current[msg.avatar_id] = {
          chunks: [],
          totalBytes: msg.total_bytes,
          avatarName: msg.avatar_name,
          utteranceType: msg.utterance_type,
        }
        break
      }

      case 'audio_chunk': {
        const acc = bufferMapRef.current[msg.avatar_id]
        if (acc) {
          acc.chunks.push(msg.data)  // base64 string
        }
        break
      }

      case 'audio_end': {
        const acc = bufferMapRef.current[msg.avatar_id]
        if (!acc || msg.cancelled) {
          delete bufferMapRef.current[msg.avatar_id]
          break
        }

        // Decode accumulated base64 → ArrayBuffer → AudioBuffer
        try {
          const ctx = getCtx()
          const b64 = acc.chunks.join('')
          const binary = atob(b64)
          const arrayBuf = new ArrayBuffer(binary.length)
          const view = new Uint8Array(arrayBuf)
          for (let i = 0; i < binary.length; i++) {
            view[i] = binary.charCodeAt(i)
          }
          const audioBuffer = await ctx.decodeAudioData(arrayBuf)

          queueRef.current.push({
            avatarId: msg.avatar_id,
            avatarName: acc.avatarName,
            utteranceType: acc.utteranceType,
            audioBuffer,
          })
          playNext()
        } catch (err) {
          console.warn('[useAudioPlayer] decode failed:', err)
        }

        delete bufferMapRef.current[msg.avatar_id]
        break
      }

      case 'avatar_speaking': {
        // Use speaking events for status badge even without audio_end
        if (!msg.speaking) {
          setSpeaking((prev) =>
            prev?.avatarId === msg.avatar_id ? null : prev
          )
        }
        break
      }

      default:
        break
    }
  }, [getCtx, playNext])

  // Clean up AudioContext on unmount
  useEffect(() => {
    return () => {
      if (ctxRef.current) {
        ctxRef.current.close().catch(() => {})
      }
    }
  }, [])

  return { handleWsMessage, speaking, cancelAll }
}
