# Codebase Quality and Design Analysis

Date: 2026-03-08
Status: Approved design

## Goal

Produce a refactor roadmap for the OBS real-time subtitle translation codebase that prioritizes long-term maintainability, while allowing a major redesign to address mixed responsibilities, weak test seams, runtime fragility, and extension cost.

## Current Observations

- `engine.py` currently owns lifecycle, queue policy, processing orchestration, adapter setup, failure handling, and callback dispatch.
- `pipeline.py` and `obs_script.py` each contain frontend-specific orchestration around the same runtime behavior.
- The codebase already has some useful behavioral tests, but the architecture still pushes too much logic through large object seams.
- Runtime control, infrastructure concerns, and processing flow are coupled tightly enough that changes in one area are likely to ripple through unrelated surfaces.

## Options Considered

### 1. Core plus adapters redesign (chosen)

Build a small application core around a live subtitle session, then move audio capture, VAD, ASR, translation, OBS delivery, CLI bootstrapping, and OBS script bootstrapping into adapters and entrypoints.

Why chosen:

- Best match for a major redesign.
- Directly attacks the current responsibility mixing.
- Creates the strongest foundation for testability and future extension.

Trade-offs:

- Highest upfront churn.
- Requires a deliberate migration plan to avoid destabilizing the runtime.

### 2. Layered modular cleanup

Keep the current overall shape but split `engine.py` into smaller services and share more glue code between CLI and OBS.

Why not chosen:

- Safer short term, but likely preserves too much conceptual coupling.
- Not strong enough for the broad set of pain points identified.

### 3. Plugin or event-bus architecture

Reframe the application around a more generic stream of events with pluggable stages and sinks.

Why not chosen:

- Powerful, but likely too abstract for the current size and maturity of the system.
- Risks overengineering before the core boundaries are clean.

## Target Architecture

The redesigned system centers on a single application core whose only job is to run a live subtitle session. The core should not know whether it is being driven by the CLI or by OBS, and it should not directly instantiate concrete audio, model, or subtitle delivery implementations.

The codebase should be split into four layers:

- `domain/`
  - Pure data types and rules: runtime state, translation result, health events, backpressure policy, and failure categories.
- `application/`
  - Session orchestration and lifecycle coordination.
- `adapters/`
  - Concrete implementations for audio capture, VAD, ASR, translation, OBS WebSocket delivery, and direct OBS-script delivery.
- `entrypoints/`
  - CLI and OBS startup code that compose the application from adapters and start or stop a session.

This removes the current pattern where `engine.py` owns both business orchestration and infrastructure control, while `pipeline.py` and `obs_script.py` duplicate delivery-specific workflow logic around it.

## Core Components

Inside the application layer, responsibilities should be split into explicit components rather than one monolithic runtime object.

### SessionController

- Owns lifecycle transitions such as `starting`, `running`, `stopping`, `stopped`, and `failed`.
- Coordinates startup, shutdown, and fatal-error handling.

### AudioIngress

- Accepts chunks from the audio adapter.
- Applies centralized buffering and backpressure rules.
- Emits normalized frames or speech-ready buffers into the processing path.

### SpeechPipeline

- Runs VAD, transcription, and translation as one processing pipeline.
- Produces typed subtitle events containing transcript, translation, latency, and language metadata.

### ResultDispatcher

- Pushes subtitle and status events to sinks.
- Keeps delivery concerns out of core processing logic.

### HealthReporter

- Tracks dropped chunks, degraded mode, adapter failures, and last error state.

## Ports and Adapters

The application core should depend on ports rather than concrete classes. The expected ports are:

- `AudioSource`
- `SpeechSegmenter`
- `Transcriber`
- `Translator`
- `SubtitleSink`
- `StatusSink`

Concrete adapters implement those ports for the real runtime. This gives the CLI and OBS script a shared core while keeping integration-specific concerns isolated.

## Data Flow

The runtime should follow one explicit, unidirectional flow:

`Entrypoint -> build adapters -> create SessionController -> start session -> audio frames in -> speech segments out -> transcription -> translation -> subtitle or status events -> sinks`

Detailed behavior:

- Startup
  - An entrypoint builds adapters from `Config`.
  - The session validates dependencies and transitions to `starting`.
  - Adapter initialization failure produces a typed startup failure and clean exit.
- Live processing
  - Audio enters through one ingress interface.
  - Backpressure policy lives in `AudioIngress` instead of being embedded in a god object.
  - VAD produces speech segments.
  - ASR and translation produce immutable subtitle events rather than immediate side-effect callbacks.
- Delivery
  - Sinks consume subtitle and status events.
  - CLI logging, OBS WebSocket updates, and direct OBS updates are just different sink implementations.
- Shutdown
  - A stop command transitions the session to `stopping`, drains or flushes what is safe, then closes adapters in a deterministic order.

This design keeps control flow separate from side effects and makes runtime behavior easier to reason about and easier to simulate in tests.

## Error Handling and Resilience

Failures should be first-class and classified explicitly rather than handled as ad hoc exceptions mixed with state mutation.

Suggested failure taxonomy:

- `StartupError`
- `AdapterError`
- `ProcessingError`
- `DeliveryError`
- `ShutdownError`

Each failure should carry:

- source
- severity
- recoverability
- user-facing message

Policy:

- Fatal failures
  - Example: unrecoverable model initialization or audio startup failure.
  - Result: transition to `failed`, emit terminal status, close resources.
- Recoverable failures
  - Example: dropped chunk, temporary sink failure, or a bad single segment.
  - Result: emit degraded status, increment counters, continue if safe.
- Operator-visible failures
  - Present clean CLI and OBS status messages rather than raw exception text where possible.

This moves failure policy into the application layer so behavior stays consistent across CLI and OBS modes.

## Testing Strategy

Testing should reflect the architecture rather than mostly probing internals through large seams.

### Unit tests

- Pure domain and application tests for lifecycle transitions, backpressure policy, error classification, and event emission.
- No threads, OBS integration, or real model loading.

### Contract tests

- Verify each adapter obeys its port contract.
- Examples: audio adapter chunk normalization, OBS sink update and clear behavior, translator adapter language mapping.

### Integration tests

- Compose the session with fakes to verify startup, success path, degraded mode, and failure shutdown.
- Serve as the main architectural safety net for refactoring.

## Code Quality Targets

The roadmap should explicitly drive the codebase toward these qualities:

- Thin entrypoints.
- No cross-layer imports from adapters into domain or application code.
- No hidden global state for runtime control.
- Deterministic lifecycle and state tests.
- Clear ownership of concurrency primitives.

Success is not just smaller files. Success means the core behavior can be tested without OBS, real audio hardware, or real models.

## Migration Phases

### Phase 1: establish the new core

- Define ports, events, failure types, and the new session lifecycle model.
- Build the new application core beside the existing runtime.

### Phase 2: migrate entrypoints

- Move CLI and OBS flows onto the new core.
- Add compatibility wrappers where needed to reduce cutover risk.

### Phase 3: remove legacy orchestration

- Delete superseded orchestration paths.
- Expand integration coverage.
- Tighten module boundaries and imports.

## Non-Goals

- Introducing a generic plugin platform for arbitrary third-party extensions.
- Changing the external product scope beyond what is needed to support the new architecture.
- Reworking the user-facing feature set before the runtime boundaries are stable.

## Design Outcome

The approved direction is a major refactor toward a core-plus-adapters architecture with explicit lifecycle management, event-driven data flow, typed failure policy, and architecture-aligned testing. This design is intended to become the basis for the implementation plan.
