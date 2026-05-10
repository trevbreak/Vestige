/**
 * useAudioPlayer — Web Audio API playback for avatar TTS audio.
 *
 * Handles two delivery modes from the backend:
 *
 *   encoding: "wav"       — legacy batch path (XTTS-v2, Edge-TTS)
 *                           Accumulates all chunks, decodes WAV on audio_end.
 *
 *   encoding: "pcm_s16le" — ElevenLabs streaming path
 *                           Decodes Int16 chunks immediately and schedules
 *                           them on a running AudioBufferSourceNode cursor,
 *                           so audio starts within ~5ms of the first chunk.
 *
 * Usage:
 *   const { handleWsMessage, speaking, cancelAll, primeAudioContext } = useAudioPlayer()
 *
 * Feed every incoming WebSocket message into handleWsMessage().
 */

import { useRef, useState, useCallback, useEffect } from 'react'

// PCM streaming: how many seconds to pre-buffer before starting playback
const PCM_PREBUFFER_S = 0.1

export function useAudioPlayer() {
  const ctxRef = useRef(null)
  // WAV accumulation map: avatar_id → { chunks, totalBytes, avatarName, utteranceType }
  const wavBufferMapRef = useRef({})
  // PCM streaming map: avatar_id → StreamingPCMPlayer
  const pcmPlayerMapRef = useRef({})

  const queueRef = useRef([])          // [{avatarId, avatarName, utteranceType, audioBuffer}]
  const playingRef = useRef(false)
  const sourceRef = useRef(null)
  const [speaking, setSpeaking] = useState(null)

  const getCtx = useCallback(() => {
    if (!ctxRef.current) {
      ctxRef.current = new (window.AudioContext || window.webkitAudioContext)()
    }
    return ctxRef.current
  }, [])

  const primeAudioContext = useCallback(async () => {
    const ctx = getCtx()
    if (ctx.state === 'suspended') await ctx.resume()
  }, [getCtx])

  const cancelAll = useCallback(() => {
    queueRef.current = []
    if (sourceRef.current) {
      try { sourceRef.current.stop() } catch {}
      sourceRef.current = null
    }
    // Stop any active PCM streamers
    for (const player of Object.values(pcmPlayerMapRef.current)) {
      player.stop()
    }
    pcmPlayerMapRef.current = {}
    wavBufferMapRef.current = {}
    setSpeaking(null)
    playingRef.current = false
  }, [])

  const playNext = useCallback(async () => {
    if (playingRef.current || queueRef.current.length === 0) return
    const job = queueRef.current.shift()
    playingRef.current = true
    setSpeaking({ avatarId: job.avatarId, avatarName: job.avatarName, utteranceType: job.utteranceType })

    const ctx = getCtx()
    if (ctx.state === 'suspended') await ctx.resume()

    const source = ctx.createBufferSource()
    sourceRef.current = source

    const gainNode = ctx.createGain()
    gainNode.gain.value = job.utteranceType === 'backchannel' ? 0.6 : 1.0
    source.connect(gainNode)
    gainNode.connect(ctx.destination)

    source.buffer = job.audioBuffer
    source.onended = () => {
      sourceRef.current = null
      playingRef.current = false
      setSpeaking(null)
      playNext()
    }
    source.start()
  }, [getCtx])

  const handleWsMessage = useCallback(async (msg) => {
    if (!msg || !msg.type) return

    switch (msg.type) {
      case 'audio_start': {
        const encoding = msg.encoding || 'wav'

        if (encoding === 'pcm_s16le') {
          // ElevenLabs streaming path — create a StreamingPCMPlayer
          const ctx = getCtx()
          if (ctx.state === 'suspended') {
            try { await ctx.resume() } catch {}
          }
          pcmPlayerMapRef.current[msg.avatar_id] = new StreamingPCMPlayer(
            ctx,
            msg.sample_rate || 24000,
            msg.avatar_name,
            msg.utterance_type,
            (avatarId, name, utType) => {
              setSpeaking({ avatarId, avatarName: name, utteranceType: utType })
            },
            () => setSpeaking(null),
          )
        } else {
          // Legacy WAV batch path
          wavBufferMapRef.current[msg.avatar_id] = {
            chunks: [],
            totalBytes: msg.total_bytes,
            avatarName: msg.avatar_name,
            utteranceType: msg.utterance_type,
          }
        }
        break
      }

      case 'audio_chunk': {
        const binary = atob(msg.data)
        const bytes = new Uint8Array(binary.length)
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)

        const pcmPlayer = pcmPlayerMapRef.current[msg.avatar_id]
        if (pcmPlayer) {
          // PCM streaming: feed chunk immediately
          pcmPlayer.pushChunk(bytes)
        } else {
          const acc = wavBufferMapRef.current[msg.avatar_id]
          if (acc) acc.chunks.push(bytes)
        }
        break
      }

      case 'audio_end': {
        const pcmPlayer = pcmPlayerMapRef.current[msg.avatar_id]
        if (pcmPlayer) {
          if (msg.cancelled) {
            pcmPlayer.stop()
          } else {
            pcmPlayer.flush()
          }
          delete pcmPlayerMapRef.current[msg.avatar_id]
          break
        }

        // WAV batch path
        const acc = wavBufferMapRef.current[msg.avatar_id]
        if (!acc || msg.cancelled) {
          delete wavBufferMapRef.current[msg.avatar_id]
          break
        }

        try {
          const ctx = getCtx()
          const totalLen = acc.chunks.reduce((s, c) => s + c.length, 0)
          const arrayBuf = new ArrayBuffer(totalLen)
          const view = new Uint8Array(arrayBuf)
          let pos = 0
          for (const chunk of acc.chunks) { view.set(chunk, pos); pos += chunk.length }
          const audioBuffer = await ctx.decodeAudioData(arrayBuf)

          queueRef.current.push({
            avatarId: msg.avatar_id,
            avatarName: acc.avatarName,
            utteranceType: acc.utteranceType,
            audioBuffer,
          })
          playNext()
        } catch (err) {
          console.warn('[useAudioPlayer] WAV decode failed:', err)
        }

        delete wavBufferMapRef.current[msg.avatar_id]
        break
      }

      case 'avatar_speaking': {
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

  useEffect(() => {
    return () => {
      if (ctxRef.current) {
        ctxRef.current.close().catch(() => {})
      }
    }
  }, [])

  return { handleWsMessage, speaking, cancelAll, primeAudioContext }
}


/**
 * StreamingPCMPlayer — plays raw int16 PCM chunks as they arrive.
 *
 * Uses a scheduled-source cursor: each pushChunk() call converts the raw
 * bytes to a float32 AudioBuffer and schedules it exactly after the previous
 * chunk ends. The first chunk is played immediately (after a tiny pre-buffer).
 */
class StreamingPCMPlayer {
  constructor(ctx, sampleRate, avatarName, utteranceType, onStart, onEnd) {
    this._ctx = ctx
    this._sampleRate = sampleRate
    this._avatarName = avatarName
    this._utteranceType = utteranceType
    this._onStart = onStart
    this._onEnd = onEnd

    this._nextTime = 0      // AudioContext time when next chunk should start
    this._started = false
    this._stopped = false
    this._pendingBytes = [] // Uint8Array chunks accumulated before playback starts
    this._pendingByteLen = 0
    this._prebufferBytes = Math.floor(sampleRate * PCM_PREBUFFER_S) * 2 // int16 = 2 bytes/sample
  }

  pushChunk(uint8chunk) {
    if (this._stopped) return
    this._pendingBytes.push(uint8chunk)
    this._pendingByteLen += uint8chunk.length

    if (!this._started && this._pendingByteLen >= this._prebufferBytes) {
      this._start()
    } else if (this._started) {
      this._scheduleAll()
    }
  }

  flush() {
    if (this._stopped) return
    if (!this._started && this._pendingBytes.length > 0) {
      this._start()
    } else {
      this._scheduleAll()
    }
    this._stopped = true
    // Notify speaking end after last scheduled chunk plays
    const remaining = Math.max(0, this._nextTime - this._ctx.currentTime)
    setTimeout(() => this._onEnd(), remaining * 1000 + 100)
  }

  stop() {
    this._stopped = true
    this._pendingBytes = []
  }

  _start() {
    this._started = true
    this._nextTime = this._ctx.currentTime + 0.005  // 5ms buffer
    this._onStart(null, this._avatarName, this._utteranceType)
    this._scheduleAll()
  }

  _scheduleAll() {
    while (this._pendingBytes.length > 0) {
      const chunk = this._pendingBytes.shift()
      this._scheduleChunk(chunk)
    }
  }

  _scheduleChunk(uint8Bytes) {
    // Convert int16 little-endian bytes → float32 samples
    const numSamples = Math.floor(uint8Bytes.length / 2)
    if (numSamples === 0) return

    const buffer = this._ctx.createBuffer(1, numSamples, this._sampleRate)
    const channelData = buffer.getChannelData(0)
    const view = new DataView(uint8Bytes.buffer, uint8Bytes.byteOffset, uint8Bytes.byteLength)

    for (let i = 0; i < numSamples; i++) {
      const int16 = view.getInt16(i * 2, true)  // little-endian
      channelData[i] = int16 / 32768.0
    }

    const source = this._ctx.createBufferSource()
    source.buffer = buffer
    source.connect(this._ctx.destination)
    source.start(this._nextTime)
    this._nextTime += buffer.duration
  }
}
