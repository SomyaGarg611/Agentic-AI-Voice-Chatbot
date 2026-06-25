# Aria — Agentic AI Voice Chatbot

A production-grade **voice-first AI research assistant** built with FastAPI. Speak your question, Aria searches the web, reads your uploaded documents, runs calculations, and answers in a natural voice — all in real time.

Built as a portfolio project showcasing **2+ years of AI engineering** across agentic tool-calling, RAG, long-term memory, observability, and a low-latency voice pipeline.

---

## Demo

```
User (voice): "Who is Somya Garg and what are her AI skills?"
Aria:         [reads uploaded resume via RAG]
              "Somya is a Software Engineer with 2+ years of experience,
               specialising in Python, LLM integrations, RAG pipelines,
               and workflow automation…"
```

---

## Architecture

```
Browser (mic + audio playback)
    │  PCM-16 audio frames        ▲  PCM-16 TTS chunks
    ▼  WebSocket /ws/voice        │
FastAPI
  ├── Deepgram Nova-2  ──────── streaming STT
  ├── Claude Sonnet 4.6 ─────── agentic tool-calling loop
  │     ├── web_search   (Tavily)
  │     ├── fetch_url    (httpx + trafilatura)
  │     ├── rag_search   (ChromaDB)
  │     └── calculator   (sympy)
  ├── ElevenLabs ────────────── sentence-streamed TTS → PCM-16
  ├── Long-term memory ──────── SQLite + ChromaDB (cross-session recall)
  └── Langfuse ──────────────── full turn + tool tracing
```

---

## Features

| Feature | Detail |
|---|---|
| **Voice pipeline** | Deepgram Nova-2 streaming STT → Claude agent → ElevenLabs TTS, <2 s first audio |
| **Agentic tool use** | Web search, URL fetch, document RAG, symbolic calculator — Claude decides which to chain |
| **RAG** | Upload PDF, Word, Excel, PowerPoint, CSV, TXT, MD, or HTML; recursive token-aware chunking tuned to the embedder, tables chunked row-wise with headers preserved |
| **Long-term memory** | Per-turn summaries stored in ChromaDB; top-k relevant memories retrieved and injected on every turn |
| **Chat history** | Multiple conversations — start new chats, browse past ones in a sidebar, reopen any to continue with full context, or delete them |
| **Barge-in** | User can interrupt mid-response; server cancels task and browser stops audio instantly |
| **Sentence streaming** | TTS synthesised sentence-by-sentence — browser starts playing before generation finishes |
| **Observability** | Langfuse 4.x traces every turn, Claude generation (with token counts), and each tool call |
| **Eval suite** | LLM-as-judge eval harness scoring faithfulness, content match, and citation presence |
| **Graceful fallback** | If Deepgram/ElevenLabs keys are absent *or* a provider fails at runtime (e.g. ElevenLabs quota), it auto-falls back to the browser's Web Speech API so STT/TTS keep working — never silent |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Uvicorn, Python 3.12+ |
| LLM | Anthropic Claude Sonnet 4.6 |
| STT | Deepgram Nova-2 (streaming WebSocket) |
| TTS | ElevenLabs (sentence-streamed PCM-16) |
| Web search | Tavily |
| URL extraction | httpx + trafilatura |
| Vector store / RAG | ChromaDB (embedded, local ONNX embeddings) |
| Document parsing | PyMuPDF (PDF), python-docx (Word), openpyxl (Excel), python-pptx (PowerPoint), trafilatura (HTML) |
| Chunking | Recursive, structure-aware, token-aware (tiktoken) splitter |
| Memory | SQLite (aiosqlite) + ChromaDB |
| Tracing | Langfuse 4.x |
| Calculator | sympy |
| Frontend | React + Vite, AudioWorklet, Web Audio API (state-reactive voice orb UI) |

---

## Project Structure

```
VoiceBot/
├── app/
│   ├── main.py                  # FastAPI app, WebSocket, REST endpoints
│   ├── config.py                # pydantic-settings (all API keys)
│   ├── agent/
│   │   ├── loop.py              # Claude tool-calling loop (Langfuse-traced)
│   │   ├── prompts.py           # System prompt + RAG-first priority rules
│   │   └── tools/
│   │       ├── web_search.py    # Tavily search
│   │       ├── fetch_url.py     # httpx + trafilatura URL reader
│   │       ├── rag_search.py    # ChromaDB semantic search
│   │       └── calculator.py    # sympy safe evaluator
│   ├── rag/
│   │   ├── store.py             # ChromaDB client + query
│   │   ├── extract.py           # Multi-format extraction (PDF/DOCX/XLSX/PPTX/CSV/HTML)
│   │   ├── splitter.py          # Recursive token-aware text splitter
│   │   └── ingest.py            # Orchestrates extract → split → index
│   ├── memory/
│   │   └── longterm.py          # Memory + chat history (SQLite + ChromaDB)
│   ├── voice/
│   │   ├── session.py           # Per-connection orchestrator + barge-in
│   │   ├── deepgram_stt.py      # Deepgram asyncwebsocket wrapper
│   │   └── elevenlabs_tts.py    # ElevenLabs streaming + markdown cleaner
│   └── observability/
│       └── tracing.py           # Langfuse 4.x context-manager tracing
├── frontend/                    # React + Vite UI (built to frontend/dist)
│   ├── src/
│   │   ├── App.jsx              # Layout: topbar, thread, orb, composer
│   │   ├── useVoiceSession.js   # WebSocket + audio pipeline + chat state hook
│   │   └── components/          # VoiceOrb, Message, Composer, Toasts, Sidebar
│   ├── public/pcm-processor.js  # AudioWorklet processor (mic → PCM-16)
│   └── dist/                    # Built static assets (served by FastAPI)
├── web/                         # Legacy vanilla UI (no-build fallback)
├── evals/
│   ├── dataset.jsonl            # Research Q&A eval cases
│   └── run_evals.py             # LLM-as-judge eval harness
├── deploy/
│   ├── Dockerfile
│   ├── docker-compose.yml       # app + Caddy HTTPS
│   ├── Caddyfile                # Auto-TLS reverse proxy
│   └── README-aws.md            # AWS free-tier deploy guide
├── .env.example
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/<your-username>/VoiceBot.git
cd VoiceBot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env and add your keys (see Keys section below)
```

### 3. Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000** in Chrome (required for mic access on localhost).

> The React UI ships pre-built in `frontend/dist`, so no Node is needed to run.
> To modify the UI: `cd frontend && npm install && npm run dev` (hot-reload dev
> server with API proxy), or `npm run build` to regenerate the production bundle.

---

## API Keys

All keys have **free tiers** sufficient for development and demos.

| Key | Service | Free tier | Where to get |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Claude LLM | Pay-per-token (~$0.01/conv) | [console.anthropic.com](https://console.anthropic.com) |
| `DEEPGRAM_API_KEY` | Streaming STT | $200 credit | [console.deepgram.com](https://console.deepgram.com) |
| `ELEVENLABS_API_KEY` | TTS voice | 10k chars/mo | [elevenlabs.io](https://elevenlabs.io) → API Keys (use a **premade** voice) |
| `TAVILY_API_KEY` | Web search | 1000 searches/mo | [app.tavily.com](https://app.tavily.com) |
| `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` | Tracing | Free cloud tier | [cloud.langfuse.com](https://cloud.langfuse.com) → Settings → API Keys |

**Without keys:** the app runs in fallback mode — browser Web Speech API handles STT/TTS, and web search is disabled. Only `ANTHROPIC_API_KEY` is required to run.

---

## Usage

| Action | How |
|---|---|
| **Voice query** | Click the 🎤 mic button (wait for "Ready" status), then speak |
| **Text query** | Type in the input box and press Enter |
| **Upload a document** | Click 📄, choose a PDF, Word, Excel, PowerPoint, CSV, TXT, MD or HTML file — then ask about it |
| **New chat** | Click ＋ (top-right) to start a fresh conversation |
| **Chat history** | Click ☰ (top-left) to open the sidebar — reopen any past chat to continue it, or delete it |
| **Stop mid-response** | Click the red ⏹ stop button or press **Escape** |
| **Interrupt** | Just speak while Aria is responding — she stops and answers your new question |

---

## Eval Suite

```bash
# Runs 5 research questions through the live agent and scores each on:
# faithfulness, content match, and citation presence (LLM-as-judge)
python evals/run_evals.py
```

---

## Deploy to AWS (Free Tier)

See [`deploy/README-aws.md`](deploy/README-aws.md) for the full step-by-step guide.

**Summary:**
1. Launch EC2 t2.micro (free 12 months), attach Elastic IP
2. Create a free [DuckDNS](https://duckdns.org) subdomain → point to Elastic IP
3. `docker compose -f deploy/docker-compose.yml up -d --build`
4. Caddy auto-provisions Let's Encrypt HTTPS — browser mic works instantly

---

## What This Demonstrates

This project was built to showcase real AI engineering skills:

| Skill | Where |
|---|---|
| **Agentic tool orchestration** | Multi-step Claude tool-calling loop with 4 tools, retry logic, citation extraction |
| **Retrieval-Augmented Generation** | Multi-format extraction (PDF/Word/Excel/PPT/CSV/HTML), recursive token-aware chunking tuned to the embedder window, row-wise table chunking, cosine relevance scoring |
| **Long-term memory** | Cross-session summarise-and-retrieve pattern (SQLite + vector store) |
| **Session management** | Client-owned chat ids; resume any past conversation with full context reloaded server-side; graceful provider fallback |
| **Real-time voice pipeline** | AudioWorklet PCM capture → Deepgram streaming STT → sentence-chunked TTS |
| **Barge-in / interruption** | asyncio task cancellation + browser AudioBufferSourceNode stop |
| **Observability** | Langfuse 4.x OTel-based tracing with token counts per generation |
| **Eval harness** | LLM-as-judge scoring on a held-out dataset |
| **Production patterns** | Pydantic settings, graceful degradation, async error handling, HTTPS deploy |

---

## License

MIT
