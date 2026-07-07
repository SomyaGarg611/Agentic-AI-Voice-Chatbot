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
  const [chats, setChats] = useState([])
  const [activeChatId, setActiveChatId] = useState(null)
  const [needAuth, setNeedAuth] = useState(false)
  const [authError, setAuthError] = useState('')
  const [authConfig, setAuthConfig] = useState({ googleClientId: '', devLogin: true })
  const [user, setUser] = useState(null)

  // refs (mutable, non-rendering)
  const ws = useRef(null)
  const activeChatRef = useRef(null)
  const tokenRef = useRef(localStorage.getItem('voicebot_token') || '')
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

  // Attach the access token (if any) to API calls
  const authFetch = useCallback((url, opts = {}) => {
    const headers = { ...(opts.headers || {}) }
    if (tokenRef.current) headers.Authorization = `Bearer ${tokenRef.current}`
    return fetch(url, { ...opts, headers })
  }, [])

  const refreshDocCount = useCallback(async () => {
    try {
      const r = await authFetch('/api/rag/stats')
      const j = await r.json()
      setDocCount(j.doc_chunks || 0)
    } catch {}
  }, [authFetch])

  // ── Chat history ──────────────────────────────────────────────────
  const newId = () =>
    (crypto.randomUUID ? crypto.randomUUID() : 'c-' + Date.now() + '-' + Math.round(performance.now()))

  const sendSession = useCallback((id) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify({ type: 'session', session_id: id }))
    }
  }, [])

  const loadChats = useCallback(async () => {
    try {
      const r = await authFetch('/api/chats')
      const j = await r.json()
      setChats(j.chats || [])
    } catch {}
  }, [authFetch])

  const newChat = useCallback(() => {
    const id = newId()
    activeChatRef.current = id
    setActiveChatId(id)
    setMessages([])
    pendingId.current = null
    liveId.current = null
    setTranscript('')
    sendSession(id)
  }, [sendSession])

  const openChat = useCallback(async (id) => {
    try {
      const r = await authFetch(`/api/chats/${id}`)
      const j = await r.json()
      const msgs = (j.messages || []).map((m, i) => ({ id: `h${i}`, role: m.role, text: m.text }))
      activeChatRef.current = id
      setActiveChatId(id)
      pendingId.current = null
      liveId.current = null
      setMessages(msgs)
      setTranscript('')
      sendSession(id)
    } catch {}
  }, [sendSession])

  const deleteChat = useCallback(async (id) => {
    try {
      await authFetch(`/api/chats/${id}`, { method: 'DELETE' })
      await loadChats()
      if (id === activeChatRef.current) newChat()
    } catch {}
  }, [authFetch, loadChats, newChat])

  // ── Audio playback ────────────────────────────────────────────────
  const getAudioCtx = useCallback(() => {
    if (!audioCtx.current || audioCtx.current.state === 'closed') {
      // Safari only exposes webkitAudioContext. Use device-native sample rate
      // (forcing 16 kHz can output silence); 16 kHz PCM is resampled on playback.
      const AC = window.AudioContext || window.webkitAudioContext
      audioCtx.current = new AC()
      nextPlayTime.current = 0
    }
    return audioCtx.current
  }, [])

  // Safari/iOS unlock: must play a real (silent) buffer inside a user gesture,
  // resume() alone isn't enough.
  const primeAudio = useCallback(() => {
    const ctx = getAudioCtx()
    try {
      const b = ctx.createBuffer(1, 1, 22050)
      const s = ctx.createBufferSource()
      s.buffer = b
      s.connect(ctx.destination)
      s.start(0)
    } catch {}
    if (ctx.state !== 'running') ctx.resume().catch(() => {})
  }, [getAudioCtx])

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
    try {
      if (!buf || buf.byteLength < 2) return
      const ctx = getAudioCtx()
      if (ctx.state === 'suspended') ctx.resume().catch(() => {})
      // PCM-16 needs an even byte length; drop a stray trailing byte if a chunk split a sample
      const usable = buf.byteLength - (buf.byteLength % 2)
      const i16 = new Int16Array(buf, 0, usable / 2)
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
    } catch {
      /* skip a bad chunk rather than break the stream */
    }
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
      const pid = pendingId.current   // capture BEFORE nulling — the updater runs later
      liveId.current = id
      pendingId.current = null
      setMessages((m) => {
        const cleared = pid ? m.filter((x) => x.id !== pid) : m
        return [...cleared, { id, role: 'agent', text }]
      })
    } else {
      const id = liveId.current
      setMessages((m) => m.map((x) => (x.id === id ? { ...x, text: x.text + text } : x)))
    }
  }, [])

  // ── WebSocket ─────────────────────────────────────────────────────
  const connect = useCallback(() => {
    setPhase(STATE.CONNECTING)
    setStatusText('Connecting')
    const url = tokenRef.current ? `${WS_URL}?token=${encodeURIComponent(tokenRef.current)}` : WS_URL
    const socket = new WebSocket(url)
    socket.binaryType = 'arraybuffer'
    ws.current = socket

    socket.onmessage = (ev) => {
      if (typeof ev.data !== 'string') { playChunk(ev.data); return }
      const msg = JSON.parse(ev.data)
      switch (msg.type) {
        case 'stt_ready':
          providerRef.current = msg.provider
          setSttProvider(msg.provider)
          // Tell the server which chat we're on (resumed or new)
          if (activeChatRef.current) sendSession(activeChatRef.current)
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
          loadChats()   // a new/updated chat now exists in history
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
        case 'notice':
          addToast('info', msg.message)
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
  }, [playChunk, pushMessage, showPending, updatePending, removePending, appendLive, speakBrowser, stopAllAudio, checkPlaybackDone, addToast, sendSession, loadChats])

  // Bring the app online once the user is signed in
  const startApp = useCallback(() => {
    setNeedAuth(false)
    loadChats()
    connect()
    refreshDocCount()
  }, [loadChats, connect, refreshDocCount])

  const _completeLogin = useCallback((path, body) => {
    setAuthError('')
    return fetch(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(async (r) => {
      const j = await r.json().catch(() => ({}))
      if (r.ok && j.token) {
        tokenRef.current = j.token
        localStorage.setItem('voicebot_token', j.token)
        localStorage.setItem('voicebot_user', JSON.stringify(j.user))
        setUser(j.user)
        // Wipe any previous user's state before showing the new account
        const id = newId()
        activeChatRef.current = id
        setActiveChatId(id)
        setMessages([])
        setChats([])
        setTranscript('')
        pendingId.current = null
        liveId.current = null
        startApp()
      } else {
        setAuthError(j.detail || 'Sign-in failed')
      }
    }).catch(() => setAuthError('Sign-in failed'))
  }, [startApp])

  const loginGoogle = useCallback((idToken) => _completeLogin('/api/auth/google', { id_token: idToken }), [_completeLogin])
  const loginDev = useCallback((email) => _completeLogin('/api/auth/dev', { email }), [_completeLogin])

  const logout = useCallback(() => {
    localStorage.removeItem('voicebot_token')
    localStorage.removeItem('voicebot_user')
    tokenRef.current = ''
    setUser(null)
    try { ws.current?.close() } catch {}
    setMessages([])
    setChats([])
    setTranscript('')
    pendingId.current = null
    liveId.current = null
    setNeedAuth(true)
  }, [])

  useEffect(() => {
    // Start on a fresh chat
    const id = newId()
    activeChatRef.current = id
    setActiveChatId(id)
    ;(async () => {
      let cfg = { google_client_id: '', dev_login: true }
      try { cfg = await (await fetch('/api/config')).json() } catch {}
      setAuthConfig({ googleClientId: cfg.google_client_id || '', devLogin: !!cfg.dev_login })
      // Resume an existing session if the stored JWT is still valid
      if (tokenRef.current) {
        const r = await authFetch('/api/chats')
        if (r.ok) {
          try { setUser(JSON.parse(localStorage.getItem('voicebot_user') || 'null')) } catch {}
          startApp()
          return
        }
        localStorage.removeItem('voicebot_token'); tokenRef.current = ''
      }
      setNeedAuth(true)
    })()
    // Unlock audio playback on the first user interaction anywhere on the page
    const unlock = () => primeAudio()
    window.addEventListener('pointerdown', unlock)
    window.addEventListener('keydown', unlock)
    return () => {
      try { ws.current?.close() } catch {}
      window.removeEventListener('pointerdown', unlock)
      window.removeEventListener('keydown', unlock)
    }
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

  // Create + unlock the AudioContext while we're inside a real user gesture,
  // so TTS playback isn't stuck in the browser's suspended state.
  const unlockAudio = useCallback(() => {
    primeAudio()
  }, [primeAudio])

  const toggleMic = useCallback(async () => {
    if (!ws.current || ws.current.readyState !== WebSocket.OPEN) return
    unlockAudio()
    if (listeningRef.current) stopMic()
    else await startMic()
  }, [startMic, stopMic, unlockAudio])

  // ── Text + upload + stop ─────────────────────────────────────────
  const sendText = useCallback((text) => {
    const t = text.trim()
    if (!t || processingRef.current) return
    if (ws.current?.readyState !== WebSocket.OPEN) return
    unlockAudio()   // we're in a click/Enter gesture — unlock playback now
    pushMessage('user', t)
    ws.current.send(JSON.stringify({ type: 'transcript', text: t }))
  }, [pushMessage, unlockAudio])

  const uploadFile = useCallback(async (file) => {
    if (!file) return
    addToast('info', `Uploading ${file.name}`)
    const fd = new FormData()
    fd.append('file', file)
    try {
      const r = await authFetch('/api/ingest', { method: 'POST', body: fd })
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
  }, [authFetch, addToast, refreshDocCount])

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
    chats, activeChatId, loadChats, newChat, openChat, deleteChat,
    needAuth, authError, authConfig, user, loginGoogle, loginDev, logout,
    toggleMic, sendText, uploadFile, stopAgent,
  }
}
