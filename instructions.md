Infrastructure Summary (Railway + LiveKit + Voice + RAG)
1) Railway Projects and Services

Create one Railway project with 4-6 services:

API (FastAPI)

Base: clone your repo (below)

Responsibilities:

Auth + tenant resolution (multi-tenant)

Call/session orchestration

RAG retrieval + LLM calls

Webhooks (Twilio events, billing events, etc.)

Session state + audit logs

LiveKit Server

Deployed as a container service on Railway

Responsibilities:

Real-time WebRTC media (voice)

Room/participant control

Notes:

You’ll set LiveKit keys/secrets as Railway env vars

Put it behind Railway’s public domain

Postgres

Railway Postgres add-on

Stores:

tenants, users, roles

call records, transcripts, events

configuration per tenant (routing rules, clinic hours, prompts)

Redis

Railway Redis add-on

Stores:

ephemeral call/session state

rate limits

job queues (optional)

RAG Vector Store (pick one)

Simplest: Managed external like Pinecone

No infra to run on Railway

All-in Railway: Postgres + pgvector (same Postgres instance)

Cheaper, fewer moving parts, good for early stage

Optional Worker Service

For async tasks:

document ingestion + embedding

transcription post-processing

analytics aggregation

2) Telephony Integration (Twilio, SIP trunks, Genesys)

You’ll need a bridge from PSTN/SIP to WebRTC.

Two common patterns:

Pattern A (Most common): Twilio SIP trunk + SIP bridge into LiveKit

Twilio receives the phone call

Twilio sends via SIP to your SIP bridge

SIP bridge joins a LiveKit room as a participant (audio in/out)

Pattern B: Provider-agnostic SIP trunk (Genesys / other carriers)

Same idea - your SIP bridge is the “front door”

Lets you swap telephony providers without changing your core platform

Key point: LiveKit is the media engine, but the SIP bridge is what makes phone networks talk to WebRTC.

3) AI Voice Pipeline (per call)

Within a LiveKit room, your backend coordinates:

Audio stream (from LiveKit participant)

STT (speech-to-text)

RAG retrieval (vector search + tenant-scoped docs)

LLM response (with tools)

TTS (text-to-speech)

Audio back into LiveKit (agent speaks)

Your FastAPI app is the conductor for all this.

4) Multi-Tenancy (what to implement in Postgres + FastAPI)

Minimum you need:

tenants table

users table

user_tenants (membership/roles)

Every call/session tagged with tenant_id

Tenant isolation rules:

enforced in API layer (and optionally DB policies)

Tenant configuration tables:

clinic hours, booking rules, call routing, prompts, knowledge-base doc sets

5) Deployment Flow on Railway

Use your existing FastAPI repo as the API service.

Put your repo link only in code (so it’s copy-paste safe):

https://github.com/engerlina/trvel-fastapi.git


Railway setup

Create new Railway project

Add “Service” → “Deploy from GitHub repo” → connect that repo

Add Postgres + Redis add-ons

Add LiveKit service (Docker image or container deployment)

Wire env vars across services

6) What “simple” looks like for onboarding (voice-only)

Self-serve flow:

Sign up (email + password / magic link)

Create tenant (clinic name, hours, locations)

Connect phone number:

provide Twilio instructions or in-app OAuth-style setup if you build it

Upload docs (pricing, services, FAQs) for RAG

Test call (sandbox phone number)

Go live

Minimal Service Map

Railway

FastAPI (from your repo)

LiveKit

Postgres (+ pgvector optional)

Redis

Worker (optional)

External

Twilio (or Genesys via SIP trunk)

Vector DB (optional external)

LLM/STT/TTS providers