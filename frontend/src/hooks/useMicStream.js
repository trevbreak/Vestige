/**
 * useMicStream — browser microphone → backend WebSocket pipeline.
 *
 * Captures audio via Web Audio API (16 kHz, mono, float32) and streams
 * 30 ms PCM chunks over a WebSocket to /ws/audio/{sessionId}.
 *
 * The server's VAD + STT pipeline processes the audio and emits transcript
 * events back over the main /ws connection.
 *
 * Usage:
 *   const { micActive, micError, startMic, stopMic, micLevel } = useMicStream(sessionId)
 */

import { useState, useRef, useCallback, useEffect } from 'react'

const SAMPLE_RATE = 16000
const CHUNK_MS = 30
const CHUNK_SAMPLES = 512  // nearest power-of-2 to 30ms@16kHz (480); ScriptProcessor requires power-of-2

export function useMicStream(sessionId) {
  const [micActive, setMicActive] = useState(false)
  const [micLoading, setMicLoading] = useState(false)
  const [micError, setMicError] = useState(null)
  const [micLevel, setMicLevel] = useState(0)  // 0-1 RMS level for UI

  const wsRef = useRef(null)
  const contextRef = useRef(null)
  const processorRef = useRef(null)
  const sourceRef = useRef(null)
  const streamRef = useRef(null)
  const sampleBufRef = useRef([])  // accumulate samples between chunk boundaries

  const stopMic = useCallback(() => {
    if (processorRef.current) {
      processorRef.current.disconnect()
      processorRef.current = null
    }
    if (sourceRef.current) {
      sourceRef.current.disconnect()
      sourceRef.current = null
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    if (contextRef.current && contextRef.current.state !== 'closed') {
      contextRef.current.close()
      contextRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    sampleBufRef.current = []
    setMicActive(false)
    setMicLoading(false)
    setMicLevel(0)
  }, [])

  const startMic = useCallback(async () => {
    if (!sessionId) {
      setMicError('No session selected')
      return
    }
    setMicError(null)
    setMicLoading(true)

    // ── Request mic permission ─────────────────────────────────────────
    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: SAMPLE_RATE,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
    } catch (e) {
      setMicError(`Mic permission denied: ${e.message}`)
      return
    }
    streamRef.current = stream

    // ── Open audio WebSocket ───────────────────────────────────────────
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const wsUrl = `${proto}://${window.location.host}/ws/audio/${sessionId}`
    const ws = new WebSocket(wsUrl)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    await new Promise((resolve, reject) => {
      ws.onopen = resolve
      ws.onerror = () => reject(new Error('Audio WebSocket failed to connect'))
      setTimeout(() => reject(new Error('Audio WebSocket timed out')), 5000)
    }).catch((e) => {
      setMicError(e.message)
      setMicLoading(false)
      stream.getTracks().forEach((t) => t.stop())
      return null
    })

    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setMicLoading(false)
      return
    }

    ws.onclose = () => {
      setMicActive(false)
      setMicLoading(false)
    }
    ws.onerror = (e) => {
      setMicError('Audio WebSocket error')
      stopMic()
    }

    // ── Set up Web Audio pipeline ──────────────────────────────────────
    let ctx
    try {
      ctx = new AudioContext({ sampleRate: SAMPLE_RATE })
    } catch (e) {
      setMicError(`AudioContext failed: ${e.message}`)
      setMicLoading(false)
      stopMic()
      return
    }
    contextRef.current = ctx

    // Log actual rate — browser may not honour 16 kHz hint
    console.log(`[useMicStream] AudioContext sampleRate: ${ctx.sampleRate} (wanted ${SAMPLE_RATE})`)
    if (ctx.sampleRate !== SAMPLE_RATE) {
      console.warn(`[useMicStream] Browser is running at ${ctx.sampleRate} Hz instead of ${SAMPLE_RATE} Hz — audio will be misinterpreted by the backend!`)
    }

    const source = ctx.createMediaStreamSource(stream)
    sourceRef.current = source

    // ScriptProcessor: capture raw float32 PCM
    // (AudioWorklet would be better but ScriptProcessor is simpler for now)
    const processor = ctx.createScriptProcessor(CHUNK_SAMPLES, 1, 1)
    processorRef.current = processor

    let _chunkCount = 0

    processor.onaudioprocess = (e) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return

      const input = e.inputBuffer.getChannelData(0)  // float32, CHUNK_SAMPLES long

      // RMS level for the mic indicator
      let sum = 0
      for (let i = 0; i < input.length; i++) sum += input[i] * input[i]
      const rms = Math.sqrt(sum / input.length)
      setMicLevel(rms)

      // Log first 10 chunks and every 100 thereafter for diagnostics
      _chunkCount++
      if (_chunkCount <= 10 || _chunkCount % 100 === 0) {
        console.log(`[useMicStream] chunk #${_chunkCount}: ${input.length} samples, rms=${rms.toFixed(4)}`)
      }

      // Send raw float32 PCM to backend
      const buf = new Float32Array(input).buffer
      try {
        wsRef.current.send(buf)
      } catch (_) {}
    }

    source.connect(processor)
    processor.connect(ctx.destination)  // must be connected to run

    setMicLoading(false)
    setMicActive(true)
  }, [sessionId, stopMic])

  // Auto-stop when sessionId changes or component unmounts
  useEffect(() => {
    return () => stopMic()
  }, [stopMic])

  return { micActive, micLoading, micError, startMic, stopMic, micLevel }
}
