# LLM Providers

Two distinct buckets:

1. **Primary LLM** — Groq (drives query synthesis, agent reasoning, the
   chatbot). Always-on.
2. **AI Visibility probes** — OpenAI / Anthropic / Google / Perplexity /
   xAI. Used to ask "does this LLM cite us when answering this query?"
   Each provider is independent; any can be skipped without breaking the
   others.

## 1. Primary LLM — Groq

Groq is OpenAI-API-compatible, so we use the `openai` SDK with a swapped
`base_url`. No second LLM client to maintain.

### Config

| Var | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `groq` | Which provider the agent system uses by default |
| `GROQ_API_KEY` | (required) | Static API key |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | OpenAI-compatible endpoint |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | 120B open-weight model hosted by Groq. Sub-second responses |
| `GROQ_MAX_TOKENS` | `4096` | Output cap per call |
| `GROQ_TEMPERATURE` | `0.2` | Low temp for deterministic agent outputs |
| `LLM_SSL_VERIFY` | `false` | Set false inside the Docker container — corp MITM proxy issue. Use a CA-bundle path in prod |

### What Groq is used for

| Feature | Where in code |
|---|---|
| Gap-pipeline Stage 1 — query synthesis | `apps/seo_ai/gap_pipeline/query_synthesis.py` reads SEMrush keywords and asks Groq for 20–30 visibility-probe queries |
| 7-agent suite (Crawler / Competitor / Technical / Narrator / etc.) | All agents under `apps/seo_ai/agents/` use the Groq client for structured JSON outputs + tool calls |
| Chatbot stateless reasoning | `apps/seo_ai/chat/` uses Groq for the assistant page |
| Gap-pipeline narrator + comparison synthesis | `gap_pipeline/comparison.py` |

### Cost

Groq pricing is per-token (~$0.50 / $0.75 per million tokens for
`gpt-oss-120b`). At realistic in-house use (~25M tokens/month for the
chatbot + agents) the bill is under $20/month.

---

## 2. AI Visibility probes — five separate providers

Stage 2 of the gap pipeline asks each LLM "what would you cite when
answering this query?" — the answer tells us how visible
`bajajlifeinsurance.com` is in AI search results. Each provider is
keyed independently; leave a key blank and that provider is silently
skipped.

### Per-provider config

| Provider | API key var | Default model var | Default model |
|---|---|---|---|
| **OpenAI** (uses `gpt-4o-mini` + web_search_preview tool) | `OPENAI_API_KEY` | `OPENAI_AI_VISIBILITY_MODEL` | `gpt-4o-mini` |
| **Anthropic** | `ANTHROPIC_API_KEY` | `ANTHROPIC_AI_VISIBILITY_MODEL` | `claude-3-5-haiku-latest` |
| **Google Gemini** | `GOOGLE_API_KEY` | `GOOGLE_AI_VISIBILITY_MODEL` | `gemini-2.0-flash` |
| **Perplexity** | `PERPLEXITY_API_KEY` | `PERPLEXITY_AI_VISIBILITY_MODEL` | `sonar` |
| **xAI (Grok)** | `XAI_API_KEY` | `XAI_AI_VISIBILITY_MODEL` | `grok-2-latest` |

Current `.env` state:
- ✅ `GOOGLE_API_KEY` set
- ✗ all other AI Visibility keys empty (those providers silently skipped)

### Shared visibility config

| Var | Default | Purpose |
|---|---|---|
| `AI_VISIBILITY_ENABLED` | `true` | Master kill switch |
| `AI_VISIBILITY_MAX_QUERIES` | `20` | Queries per provider per run |
| `AI_VISIBILITY_REQUEST_TIMEOUT_SEC` | `30` | Per-call timeout |
| `AI_VISIBILITY_CACHE_TTL` | `604800` (7 days) | Disk cache TTL |
| `AI_VISIBILITY_SSL_VERIFY` | `false` | Corp MITM bypass |

### Per-call shape

Each probe call:
- Prompt: ~400 tokens system + 50 tokens query
- Web search retrieved (for providers that ground): ~3–5k tokens fed back as input
- Response: ~2.5k tokens answer + ~1k tokens citation extraction
- **Total billed input: ~5,000 tokens. Total billed output: ~3,500 tokens.**

### Cost per pipeline run at full settings (5 providers × 20 queries)

```
~100 calls × 5k in × $0.x/MTok input + ~100 calls × 3.5k out × $0.y/MTok output
```

Typical cost: **$1–$2 per full visibility-probe run** across all 5
providers, with the heavy ones being OpenAI (web search adds $25/1k
calls) and Anthropic Opus (if used).

## Code map

| File | Responsibility |
|---|---|
| `apps/seo_ai/llm.py` | Shared LLM client (OpenAI-compatible) — used by all Groq calls |
| `apps/seo_ai/adapters/ai_visibility/` | One subdirectory per provider with the same `probe(query) -> AIVisibilityResult` interface |
| `apps/seo_ai/adapters/ai_visibility/base.py` | Common base class + `AdapterDisabledError` (raised when the key is missing → silently skipped by the agent) |
| `apps/seo_ai/gap_pipeline/llm_search.py` | Stage 2 — runs every provider × every query in parallel |

## How it's used by the dashboard

| UI surface | LLM data used |
|---|---|
| Chat page (`/`) | Groq |
| All 7-agent runs | Groq |
| Gap pipeline → "What each LLM answered" section | All 5 AI Visibility providers (when keyed) |
| Gap pipeline → Top competitors scoring | Aggregated citation counts across all 5 probes |

## Caching

Disk caches per provider at `backend/data/_ai_visibility_cache/`.
Cache TTL 7 days. Cache key = `sha1(provider | model | query)`.

## Operator notes

- To enable a new visibility provider, just set its key in `.env` and
  restart the backend container. The adapter auto-discovers and starts
  using it on the next gap pipeline run.
- For zero-cost dev work, leave every visibility key blank — Stage 2
  reports `0 probes across 0 providers` and the pipeline keeps running.
- Groq is currently the only LLM the chatbot + agents depend on. If
  `GROQ_API_KEY` is missing, both those features fail to start.
