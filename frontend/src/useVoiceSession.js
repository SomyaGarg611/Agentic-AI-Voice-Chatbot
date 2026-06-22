import { useCallback, useEffect, useRef, useState } from 'react'

const SAMPLE_RATE = 16000
const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/voice`

// Agent state → drives the orb colour/motion. Order of precedence handled by caller.
export const STATE = {
  CONNECTING: 'connecting',
  IDLE: 'idle',
  LISTENING: 'listening',
  THINKING: 'thinking',
  SPEAKING: 'speaking',
  ERROR: 'error',
}

const TOOL_LABELS = {
  web_search: 'Searching the web',
  fetch_url: 'Reading a source',
  rag_search: 'Checking your documents',
  calculator: 'Calculating',
}

let toastId = 0

export function useVoiceSession() {
  const [phase, setPhase] = useState(STATE.CONNECTING)
  const [statusText, setStatusText] = useState('Connecting')
  const [messages, setMessages] = useState([]) // {id, role, text, pending, tool}
  const [transcript, setTranscript] = useState('')
  const [isListening, setIsListening] = useState(false)
  const [sttProvider, setSttProvider] = useState('browser')
  const [docCount, setDocCount] = useState(0)
  const [toasts, setToasts] = useState([])

  // refs (mutable, non-rendering)
  const ws = useRef(null)
  const audioCtx = useRef(null)
  const workletNode = useRef(null)
  const mediaStream = useRef(null)
  const speechRec = useRef(null)
  const activeSources = useRef([])
  const nextPlayTime = useRef(0)
  const processingRef = useRef(false)
  const listeningRef = useRef(false)
  const providerRef = useRef('browser')
  const pendingId = useRef(null)
  const liveId = useRef(null)

  const addToast = useCallback((type, message, ttl = 4000) => {
    const id = ++toastId
    setToasts((t) => [...t, { id, type, message }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), ttl)
  }, [])

  const refreshDocCount = useCallback(async () => {
    try {
      const r = await fetch('/api/rag/stats')
      const j = await r.json()
      setDocCount(j.doc_chunks || 0)
    } catch {}
  }, [])

  // ── Audio playback ────────────────────────────────────────────────
  const getAudioCtx = useCallback(() => {
    if (!audioCtx.current || audioCtx.current.state === 'closed') {
      audioCtx.current = new AudioContext({ sampleRate: SAMPLE_RATE })
      nextPlayTime.current = 0
    }
    return audioCtx.current
  }, [])

  const stopAllAudio = useCallback(() => {
    activeSources.current.forEach((s) => { try { s.stop(); s.disconnect() } catch {} })
    activeSources.current = []
    nextPlayTime.current = audioCtx.current ? audioCtx.current.currentTime : 0
  }, [])

  const checkPlaybackDone = useCallback(() => {
    if (!processingRef.current && activeSources.current.length === 0) {
      setPhase(listeningRef.current ? STATE.LISTENING : STATE.IDLE)
      setStatusText(listeningRef.current ? 'Listening' : 'Ready')
    }
  }, [])

  const playChunk = useCallback((buf) => {
    if (!buf || buf.byteLength === 0) return
    const ctx = getAudioCtx()
    const i16 = new Int16Array(buf)
    const f32 = new Float32Array(i16.length)
    for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768
    const audioBuf = ctx.createBuffer(1, f32.length, SAMPLE_RATE)
    audioBuf.getChannelData(0).set(f32)
    const src = ctx.createBufferSource()
    src.buffer = audioBuf
    src.connect(ctx.destination)
    activeSources.current.push(src)
    src.onended = () => {
      activeSources.current = activeSources.current.filter((s) => s !== src)
      checkPlaybackDone()
    }
    const startAt = Math.max(ctx.currentTime + 0.01, nextPlayTime.current)
    src.start(startAt)
    nextPlayTime.current = startAt + audioBuf.duration
  }, [getAudioCtx, checkPlaybackDone])

  const speakBrowser = useCallback((text) => {
    if (!window.speechSynthesis) return
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text.replace(/[*_#`[\]]/g, ''))
    u.rate = 1.1
    window.speechSynthesis.speak(u)
  }, [])

  // ── Message helpers ───────────────────────────────────────────────
  const pushMessage = useCallback((role, text) => {
    setMessages((m) => [...m, { id: ++toastId + '-m', role, text }])
  }, [])

  const showPending = useCallback((tool) => {
    const id = 'pending-' + (++toastId)
    pendingId.current = id
    setMessages((m) => [...m, { id, role: 'agent', pending: true, tool }])
  }, [])

  const updatePending = useCallback((tool) => {
    setMessages((m) => m.map((x) => (x.id === pendingId.current ? { ...x, tool } : x)))
  }, [])

  const removePending = useCallback(() => {
    if (!pendingId.current) return
    const id = pendingId.current
    pendingId.current = null
    setMessages((m) => m.filter((x) => x.id !== id))
  }, [])

  // Append streamed answer text into a single growing agent bubble
  const appendLive = useCallback((text) => {
    if (!liveId.current) {
      const id = 'live-' + (++toastId)
      liveId.current = id
      setMessages((m) => {
        const cleared = pendingId.current ? m.filter((x) => x.id !== pendingId.current) : m
        return [...cleared, { id, role: 'agent', text }]
      })
      pendingId.current = null
    } else {
      const id = liveId.current
      setMessages((m) => m.map((x) => (x.id === id ? { ...x, text: x.text + text } : x)))
    }
  }, [])

  // ── WebSocket ─────────────────────────────────────────────────────
  const connect = useCallback(() => {
    setPhase(STATE.CONNECTING)
    setStatusText('Connecting')
    const socket = new WebSocket(WS_URL)
    socket.binaryType = 'arraybuffer'
    ws.current = socket

    socket.onmessage = (ev) => {
      if (typeof ev.data !== 'string') { playChunk(ev.data); return }
      const msg = JSON.parse(ev.data)
      switch (msg.type) {
        case 'stt_ready':
          providerRef.current = msg.provider
          setSttProvider(msg.provider)
          setPhase(STATE.IDLE)
          setStatusText('Ready')
          break
        case 'transcript':
          setTranscript(msg.text || '')
          if (msg.is_final && msg.text) {
            pushMessage('user', msg.text)
            setTranscript('')
          }
          break
        case 'agent_thinking':
          processingRef.current = true
          liveId.current = null
          setPhase(STATE.THINKING)
          setStatusText('Thinking')
          showPending(null)
          break
        case 'tool_use':
          setStatusText(TOOL_LABELS[msg.tool] || 'Thinking')
          updatePending(msg.tool)
          break
        case 'agent_delta':
          appendLive(msg.text)
          break
        case 'agent_done':
          if (!msg.has_audio && msg.text) speakBrowser(msg.text)
          liveId.current = null
          break
        case 'audio_start':
          stopAllAudio()
          setPhase(STATE.SPEAKING)
          setStatusText('Speaking')
          break
        case 'audio_end':
          processingRef.current = false
          checkPlaybackDone()
          break
        case 'interrupt':
          stopAllAudio()
          processingRef.current = false
          removePending()
          liveId.current = null
          setTranscript('')
          setPhase(listeningRef.current ? STATE.LISTENING : STATE.IDLE)
          setStatusText(listeningRef.current ? 'Listening' : 'Ready')
          break
        case 'error':
          removePending()
          pushMessage('agent', `Something went wrong — ${msg.message}`)
          processingRef.current = false
          setPhase(STATE.ERROR)
          setStatusText('Error')
          setTimeout(() => { setPhase(STATE.IDLE); setStatusText('Ready') }, 4000)
          break
        default:
          break
      }
    }

    socket.onerror = () => { setPhase(STATE.ERROR); setStatusText('Connection error') }
    socket.onclose = () => {
      setPhase(STATE.ERROR)
      setStatusText('Disconnected')
      setTimeout(connect, 3000)
    }
  }, [playChunk, pushMessage, showPending, updatePending, removePending, appendLive, speakBrowser, stopAllAudio, checkPlaybackDone])

  useEffect(() => {
    connect()
    refreshDocCount()
    return () => { try { ws.current?.close() } catch {} }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Mic ───────────────────────────────────────────────────────────
  const startWorklet = useCallback(async (ctx, stream) => {
    await ctx.audioWorklet.addModule('/pcm-processor.js')
    const source = ctx.createMediaStreamSource(stream)
    const node = new AudioWorkletNode(ctx, 'pcm-processor')
    workletNode.current = node
    node.port.onmessage = (e) => {
      if (ws.current?.readyState === WebSocket.OPEN && !processingRef.current) {
        ws.current.send(e.data)
      }
    }
    source.connect(node)
    const silent = ctx.createGain()
    silent.gain.value = 0
    node.connect(silent)
    silent.connect(ctx.destination)
  }, [])

  const startBrowserSTT = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) { addToast('error', 'Speech recognition needs Chrome.'); return }
    const rec = new SR()
    rec.continuous = true
    rec.interimResults = true
    rec.lang = 'en-US'
    rec.onresult = (ev) => {
      const r = ev.results[ev.results.length - 1]
      const text = r[0].transcript
      setTranscript(text)
      if (r.isFinal && text.trim()) {
        setTranscript('')
        pushMessage('user', text)
        ws.current?.send(JSON.stringify({ type: 'transcript', text }))
      }
    }
    rec.onend = () => { if (listeningRef.current && !processingRef.current) rec.start() }
    rec.start()
    speechRec.current = rec
  }, [addToast, pushMessage])

  const startMic = useCallback(async () => {
    try {
      setStatusText('Requesting mic')
      mediaStream.current = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
      })
      const ctx = getAudioCtx()
      if (providerRef.current === 'deepgram') {
        await startWorklet(ctx, mediaStream.current)
        ws.current?.send(JSON.stringify({ type: 'audio_config', sample_rate: ctx.sampleRate }))
      } else {
        startBrowserSTT()
      }
      listeningRef.current = true
      setIsListening(true)
      setPhase(STATE.LISTENING)
      setStatusText('Listening')
    } catch (err) {
      setPhase(STATE.ERROR)
      setStatusText('Mic blocked')
      addToast('error', 'Microphone access denied. Allow it in the address bar.')
    }
  }, [getAudioCtx, startWorklet, startBrowserSTT, addToast])

  const stopMic = useCallback(() => {
    workletNode.current?.disconnect(); workletNode.current = null
    mediaStream.current?.getTracks().forEach((t) => t.stop()); mediaStream.current = null
    if (speechRec.current) { speechRec.current.stop(); speechRec.current = null }
    listeningRef.current = false
    setIsListening(false)
    setTranscript('')
    setPhase(processingRef.current ? STATE.THINKING : STATE.IDLE)
    setStatusText(processingRef.current ? 'Thinking' : 'Ready')
  }, [])

  const toggleMic = useCallback(async () => {
    if (!ws.current || ws.current.readyState !== WebSocket.OPEN) return
    if (audioCtx.current?.state === 'suspended') await audioCtx.current.resume()
    if (listeningRef.current) stopMic()
    else await startMic()
  }, [startMic, stopMic])

  // ── Text + upload + stop ─────────────────────────────────────────
  const sendText = useCallback((text) => {
    const t = text.trim()
    if (!t || processingRef.current) return
    if (ws.current?.readyState !== WebSocket.OPEN) return
    pushMessage('user', t)
    ws.current.send(JSON.stringify({ type: 'transcript', text: t }))
  }, [pushMessage])

  const uploadFile = useCallback(async (file) => {
    if (!file) return
    addToast('info', `Uploading ${file.name}`)
    const fd = new FormData()
    fd.append('file', file)
    try {
      const r = await fetch('/api/ingest', { method: 'POST', body: fd })
      const j = await r.json()
      if (r.ok) {
        addToast('success', `${file.name} indexed — ${j.chunks_indexed} chunks`)
        refreshDocCount()
      } else {
        addToast('error', `Upload failed: ${j.detail}`)
      }
    } catch (e) {
      addToast('error', `Upload error: ${e.message}`)
    }
  }, [addToast, refreshDocCount])

  const stopAgent = useCallback(() => {
    stopAllAudio()
    processingRef.current = false
    removePending()
    ws.current?.send(JSON.stringify({ type: 'stop' }))
    setPhase(listeningRef.current ? STATE.LISTENING : STATE.IDLE)
    setStatusText(listeningRef.current ? 'Listening' : 'Ready')
  }, [stopAllAudio, removePending])

  // Escape key stops the agent
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && processingRef.current) stopAgent() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [stopAgent])

  const isBusy = phase === STATE.THINKING || phase === STATE.SPEAKING

  return {
    phase, statusText, messages, transcript, isListening, isBusy,
    sttProvider, docCount, toasts,
    toggleMic, sendText, uploadFile, stopAgent,
  }
}
