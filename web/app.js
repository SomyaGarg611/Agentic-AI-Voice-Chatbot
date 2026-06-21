/* ═══════════════════════════════════════════════════════════════════════
   VoiceBot — Browser client
   - Mic → AudioWorklet → PCM-16 → WebSocket → Deepgram (server-side)
   - Fallback: Web Speech API for both STT and TTS when keys unavailable
   - Receives PCM-16 audio chunks back and plays via Web Audio API
═══════════════════════════════════════════════════════════════════════ */

const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/voice`;
const SAMPLE_RATE = 16000;

// ── State ──────────────────────────────────────────────────────────────
let ws = null;
let audioCtx = null;
let workletNode = null;
let mediaStream = null;
let isListening = false;
let isProcessing = false;
let sttProvider = 'browser';   // 'deepgram' | 'browser'
let nextPlayTime = 0;
let speechRecognition = null;
let thinkingMsgEl = null;
let activeSources = [];         // AudioBufferSourceNodes currently playing

// ── DOM refs ───────────────────────────────────────────────────────────
const micBtn = document.getElementById('micBtn');
const stopBtn = document.getElementById('stopBtn');
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const chatArea = document.getElementById('chatArea');
const liveTranscript = document.getElementById('liveTranscript');
const transcriptBar = document.getElementById('transcriptBar');
const welcomeMsg = document.getElementById('welcomeMsg');
const textInput = document.getElementById('textInput');

// ── Connect WebSocket ──────────────────────────────────────────────────
function connect() {
  setStatus('connecting', 'Connecting…');
  ws = new WebSocket(WS_URL);
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => {
    setStatus('connecting', 'Connecting mic…');
    micBtn.disabled = true;
  };

  ws.onmessage = (ev) => {
    if (typeof ev.data === 'string') {
      handleJsonMessage(JSON.parse(ev.data));
    } else {
      handleAudioChunk(ev.data);
    }
  };

  ws.onerror = () => setStatus('error', 'Connection error');
  ws.onclose = () => {
    setStatus('error', 'Disconnected — reload to reconnect');
    setTimeout(connect, 3000);
  };
}

// ── JSON message handler ───────────────────────────────────────────────
function handleJsonMessage(msg) {
  switch (msg.type) {
    case 'connected':
      break;

    case 'stt_ready':
      sttProvider = msg.provider;
      micBtn.disabled = false;
      micBtn.title = `Click to speak (${msg.provider} STT)`;
      setStatus('connected', `Ready — click 🎤 to speak`);
      break;

    case 'transcript':
      if (msg.text) liveTranscript.textContent = msg.text;
      if (msg.is_final && msg.text) {
        appendUserMessage(msg.text);
        liveTranscript.textContent = '';
      }
      break;

    case 'agent_thinking':
      isProcessing = true;
      stopBtn.style.display = 'flex';
      setStatus('thinking', 'Thinking…');
      thinkingMsgEl = appendThinking();
      break;

    case 'agent_response':
      if (thinkingMsgEl) { thinkingMsgEl.remove(); thinkingMsgEl = null; }
      appendAgentMessage(msg.text);
      // If no ElevenLabs, speak via browser TTS
      if (!msg.has_audio) speakBrowser(msg.text);
      break;

    case 'audio_start':
      stopAllAudio();   // kill any previous response still playing
      setStatus('speaking', 'Speaking…');
      break;

    case 'sentence_start':
      break;

    case 'sentence_end':
      break;

    case 'audio_end':
      isProcessing = false;
      // Don't hide the stop button yet — audio is still playing in the browser.
      // _checkPlaybackDone() will hide it once the last source node finishes.
      _checkPlaybackDone();
      break;

    case 'interrupt':
      stopAllAudio();
      isProcessing = false;
      stopBtn.style.display = 'none';
      if (thinkingMsgEl) { thinkingMsgEl.remove(); thinkingMsgEl = null; }
      setStatus('connected', isListening ? '🎙 Listening…' : 'Ready — click 🎤 to speak');
      break;

    case 'error':
      if (thinkingMsgEl) { thinkingMsgEl.remove(); thinkingMsgEl = null; }
      appendAgentMessage(`⚠ ${msg.message}`);
      isProcessing = false;
      setStatus('error', 'Error');
      setTimeout(() => setStatus('connected', 'Ready'), 3000);
      break;

    case 'pong':
      break;
  }
}

// ── PCM-16 audio playback ──────────────────────────────────────────────
function getAudioCtx() {
  if (!audioCtx || audioCtx.state === 'closed') {
    audioCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
    nextPlayTime = 0;
  }
  return audioCtx;
}

function handleAudioChunk(arrayBuffer) {
  if (!arrayBuffer || arrayBuffer.byteLength === 0) return;
  const ctx = getAudioCtx();
  const int16 = new Int16Array(arrayBuffer);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    float32[i] = int16[i] / 32768.0;
  }
  const buffer = ctx.createBuffer(1, float32.length, SAMPLE_RATE);
  buffer.getChannelData(0).set(float32);
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(ctx.destination);
  activeSources.push(source);
  source.onended = () => {
    activeSources = activeSources.filter(s => s !== source);
    _checkPlaybackDone();
  };
  const startAt = Math.max(ctx.currentTime + 0.01, nextPlayTime);
  source.start(startAt);
  nextPlayTime = startAt + buffer.duration;
}

function stopAllAudio() {
  activeSources.forEach(src => { try { src.stop(); src.disconnect(); } catch (_) {} });
  activeSources = [];
  if (audioCtx) nextPlayTime = audioCtx.currentTime;
  else nextPlayTime = 0;
}

function _checkPlaybackDone() {
  // Hide the stop button and update status only once:
  //   • the server is done sending (isProcessing = false), AND
  //   • all audio nodes have finished playing (activeSources is empty)
  if (!isProcessing && activeSources.length === 0) {
    stopBtn.style.display = 'none';
    setStatus('connected', isListening ? '🎙 Listening…' : 'Ready — click 🎤 to speak');
  }
}

// ── Mic toggle ─────────────────────────────────────────────────────────
async function toggleMic() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  // Resume AudioContext on first user gesture (browser policy)
  if (audioCtx && audioCtx.state === 'suspended') await audioCtx.resume();

  if (isListening) {
    stopMic();
  } else {
    await startMic();
  }
}

async function startMic() {
  try {
    setStatus('connecting', 'Requesting mic permission…');
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 }
    });
    setStatus('connecting', 'Starting audio pipeline…');
    const ctx = getAudioCtx();

    if (sttProvider === 'deepgram') {
      await startWorklet(ctx, mediaStream);
      // Tell the server the actual sample rate so Deepgram is configured correctly
      ws.send(JSON.stringify({ type: 'audio_config', sample_rate: ctx.sampleRate }));
      setStatus('connected', '🎙 Listening via Deepgram — speak now');
    } else {
      startBrowserSTT();
      setStatus('connected', '🎙 Listening via browser — speak now');
    }

    isListening = true;
    micBtn.classList.add('active');
  } catch (err) {
    console.error('Mic error:', err);
    setStatus('error', `Mic error: ${err.message}`);
    alert(`Could not access microphone:\n${err.message}\n\nPlease allow mic access in the address bar and reload.`);
  }
}

function stopMic() {
  if (workletNode) { workletNode.disconnect(); workletNode = null; }
  if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
  if (speechRecognition) { speechRecognition.stop(); speechRecognition = null; }
  isListening = false;
  micBtn.classList.remove('active');
  liveTranscript.textContent = '';
  setStatus('connected', 'Ready');
}

// ── AudioWorklet (Deepgram path) ───────────────────────────────────────
async function startWorklet(ctx, stream) {
  // Load the processor from a static file — more reliable than Blob URLs
  await ctx.audioWorklet.addModule('/pcm-processor.js');

  const source = ctx.createMediaStreamSource(stream);
  workletNode = new AudioWorkletNode(ctx, 'pcm-processor');

  let frameCount = 0;
  workletNode.port.onmessage = (e) => {
    if (ws && ws.readyState === WebSocket.OPEN && !isProcessing) {
      ws.send(e.data);
      frameCount++;
      if (frameCount === 1) {
        liveTranscript.textContent = '🎙 Speak now…';
      }
    }
  };

  source.connect(workletNode);

  // Keep worklet alive — some browsers GC unconnected AudioNodes
  const silentGain = ctx.createGain();
  silentGain.gain.value = 0;
  workletNode.connect(silentGain);
  silentGain.connect(ctx.destination);
}

// ── Browser STT fallback (Web Speech API) ─────────────────────────────
function startBrowserSTT() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    alert('Speech recognition not supported in this browser. Please use Chrome.');
    return;
  }
  speechRecognition = new SpeechRecognition();
  speechRecognition.continuous = true;
  speechRecognition.interimResults = true;
  speechRecognition.lang = 'en-US';

  speechRecognition.onresult = (ev) => {
    const result = ev.results[ev.results.length - 1];
    const text = result[0].transcript;
    liveTranscript.textContent = text;
    if (result.isFinal && text.trim()) {
      liveTranscript.textContent = '';
      appendUserMessage(text);
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'transcript', text }));
      }
    }
  };
  speechRecognition.onerror = (e) => console.warn('SR error', e.error);
  speechRecognition.onend = () => { if (isListening && !isProcessing) speechRecognition.start(); };
  speechRecognition.start();
}

// ── Browser TTS fallback ───────────────────────────────────────────────
function speakBrowser(text) {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utt = new SpeechSynthesisUtterance(text);
  utt.rate = 1.1;
  window.speechSynthesis.speak(utt);
}

// ── Text input ─────────────────────────────────────────────────────────
function sendTyped() {
  const text = textInput.value.trim();
  if (!text || isProcessing) return;
  textInput.value = '';
  sendTextQuery(text);
}

function sendTextQuery(text) {
  if (!ws || ws.readyState !== WebSocket.OPEN || isProcessing) return;
  appendUserMessage(text);
  ws.send(JSON.stringify({ type: 'transcript', text }));
}

// ── File upload for RAG ────────────────────────────────────────────────
async function uploadFile(input) {
  const file = input.files[0];
  if (!file) return;
  input.value = '';
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch('/api/ingest', { method: 'POST', body: fd });
    const json = await res.json();
    if (res.ok) {
      showSystemMsg(`📄 "${file.name}" indexed (${json.chunks_indexed} chunks)`);
      refreshDocCount();
    } else {
      showSystemMsg(`⚠ Upload failed: ${json.detail}`);
    }
  } catch (e) {
    showSystemMsg(`⚠ Upload error: ${e.message}`);
  }
}

async function refreshDocCount() {
  try {
    const res = await fetch('/api/rag/stats');
    const json = await res.json();
    const badge = document.getElementById('docCount');
    if (json.doc_chunks > 0) {
      badge.textContent = `${json.doc_chunks} chunks`;
      badge.style.display = 'block';
    }
  } catch {}
}

// ── UI helpers ─────────────────────────────────────────────────────────
function setStatus(state, text) {
  statusDot.className = `status-dot ${state}`;
  statusText.textContent = text;
}

function hideWelcome() {
  if (welcomeMsg) welcomeMsg.style.display = 'none';
}

function appendUserMessage(text) {
  hideWelcome();
  const el = createBubble('user', '🧑', text);
  chatArea.appendChild(el);
  scrollBottom();
}

function appendAgentMessage(text) {
  hideWelcome();
  const el = createBubble('agent', '🔬', formatResponse(text));
  chatArea.appendChild(el);
  scrollBottom();
  return el;
}

function appendThinking() {
  hideWelcome();
  const el = document.createElement('div');
  el.className = 'msg agent';
  el.innerHTML = `
    <div class="avatar">🔬</div>
    <div class="bubble">
      <div class="thinking-indicator"><span></span><span></span><span></span></div>
    </div>`;
  chatArea.appendChild(el);
  scrollBottom();
  return el;
}

function showSystemMsg(text) {
  const el = document.createElement('div');
  el.style.cssText = 'text-align:center;font-size:12px;color:var(--text-muted);padding:4px 0';
  el.textContent = text;
  chatArea.appendChild(el);
  scrollBottom();
}

function createBubble(role, avatar, html) {
  const el = document.createElement('div');
  el.className = `msg ${role}`;
  el.innerHTML = `<div class="avatar">${avatar}</div><div class="bubble">${html}</div>`;
  return el;
}

function formatResponse(text) {
  // Extract [1] URL citations and turn them into links
  let out = text.replace(/\[(\d+)\]\s*(https?:\/\/\S+)/g, (_, n, url) => {
    return `<a href="${url}" target="_blank" rel="noopener">[${n}]</a>`;
  });
  return out;
}

function scrollBottom() {
  requestAnimationFrame(() => { chatArea.scrollTop = chatArea.scrollHeight; });
}

// ── Stop agent ─────────────────────────────────────────────────────────
function stopAgent() {
  stopAllAudio();
  isProcessing = false;
  stopBtn.style.display = 'none';
  if (thinkingMsgEl) { thinkingMsgEl.remove(); thinkingMsgEl = null; }
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'stop' }));
  }
  setStatus('connected', isListening ? '🎙 Listening…' : 'Ready — click 🎤 to speak');
}

// Escape key stops the agent; Enter submits text input
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && isProcessing) {
    stopAgent();
  }
});

// ── Init ────────────────────────────────────────────────────────────────
connect();
refreshDocCount();
