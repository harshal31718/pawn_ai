# PAWN — Personal AI Workspace
## Project Overview

---

## Problem Statement

Power users and casual AI users alike juggle multiple LLM platforms — ChatGPT, Gemini,
Claude — each with separate contexts, separate rate limits, and no unified memory.
Switching platforms means losing context, hitting rate limits kills workflows, and there is
no single place where all AI interactions live with persistent, personal memory.

Free-tier rate limits compound this: each provider imposes daily and per-minute caps. The
same underlying model weights are often hosted across multiple providers, each with their
own independent quota — but users have no way to exploit this automatically. Users need one
interface that brings all models together, with their own data and compute, that manages
rate limits transparently so the conversation never dies.

---

## The Core Idea

A web-based personal AI workspace where:
- Users bring their own API keys (BYOK) — Google, Cerebras, HuggingFace, GitHub Models, OpenRouter
- All models share one chat session and one context
- Rate limits are managed transparently — same model, multiple provider hosts, automatic failover
- Memory and documents live on the user's own Google Drive (Phase 2+)
- The platform is purely orchestration and interface — zero compute or storage cost to run

---

## What Makes It Different

**One context, multiple brains.**
Switch models mid-conversation without losing history. The user picks the model; the
platform picks the host.

**Rate-limit resilience.**
Same weights, multiple hosts. Automatic failover at 90% of a known limit or on a live 429.
The user always sees "Llama 3.3 70B" — not "HuggingFace" or "Cerebras". The host is an
implementation detail.

**Your data, your Drive.**
The platform durably stores nothing. All memory, conversation logs, and uploaded documents
live on the user's own Google Drive — the single source of truth. (The backend keeps a
rebuildable search index — embedded chunks in self-hosted Postgres/pgvector — derived
entirely from Drive content; `rebuild_index` can re-create it from Drive at any time.
Losing the index loses nothing.)

**BYOK.**
User's API spend. User's compute. User's storage. Platform is the product.

**Capability-aware agent routing.**
Models are categorised as Fast / Balanced / Research. Agent sub-tasks are routed by
capability level, never by hardcoded provider names. If Cerebras is rate-limited, the
resolver picks the next available balanced-tier host transparently.

---

## Target Audience

- Casual users who use AI daily but are frustrated by rate limits and context loss
- People who want a personal AI that knows them and their projects across sessions
- Users comfortable adding API keys with guided setup

---

## Provider Strategy

| Provider | Models | Free Tier | Key Type |
|---|---|---|---|
| Google | Gemini 2.5 Flash, Gemini Flash Lite, Gemini Flash Live (internal), text-embedding-004 | Yes (per-model daily caps) | BYOK |
| Cerebras | GPT-OSS 120B, GLM 4.7 | Yes (14,400 rpd) | BYOK |
| HuggingFace | Llama 3.3 70B, DeepSeek R1, others | Yes (varies) | BYOK |
| GitHub Models | Llama 3.3 70B, DeepSeek R1, Mistral | Yes (150 rpd) | BYOK |
| OpenRouter | Llama 3.3 70B:free, DeepSeek R1:free, others | Yes (200 rpm) | BYOK |

All providers except Google use the OpenAI-compatible API format — one provider path handles
all of them. Google uses an OpenAI-compatible REST endpoint
(`https://generativelanguage.googleapis.com/v1beta/openai`) — zero special cases in the
provider layer; everything is URL-routed.

---

## Build Phases

```
Phase 1    Solo local — chat UI, multi-provider, streaming (Steps 1–11)
Phase 1.5  Memory & agent — persistence, RAG, LangGraph (Steps 12–16)
Phase 1.6  Rate-limit resilience — registry, resolver, failover (Steps R1–R4)
Phase 2    Google Drive — conversation logs, memory file, uploaded docs
Phase 3    Encryption — WebCrypto AES-256-GCM, passphrase-derived key
Phase 4    Multi-user / Auth — Google OAuth2, multi-user sessions
```

Phase 1.6 is developed on a feature branch (`dev/rate-limit-resilience`) on top of main
and merges before Phase 2 starts.

---

## Business Model

- Zero infra cost — user API keys handle all compute
- Zero storage cost — user Google Drive handles all memory
- Platform monetisation path:
  - Free tier: limited agents / models
  - Pro tier: unlimited agents, deep agent mode, advanced RAG
  - Team tier: shared Drive context, collaborative agents
