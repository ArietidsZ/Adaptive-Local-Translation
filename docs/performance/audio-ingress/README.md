# Audio ingress wakeup (2026-10-30)

Baseline: `8494c598cddcf5cd8adfe9fead24cf7d9fbd3d09`. Candidate: sibling commit containing this report. Run `PROBE_LABEL=<label> PYTHONPATH=<checkout> python docs/performance/audio-ingress/probe.py` with the CI offline dependencies. The probe uses fake capture, integer chunks and a no-op consumer; no microphone, GPU, model, network or OBS is used. Raw samples are included.

In 100 serial samples with prescribed inter-arrival phases 0/2/6/9 ms, enqueue-call start to drain-callback entry had median **5.922→0.0629 ms**, nearest-rank p95 **10.140→0.345 ms**. In a separate 0.5-second empty interval, additional Event.wait calls were **49→0**. Both drain threads joined. Host scheduling is uncontrolled; these are synthetic observations, not production p95, CPU/power savings, ASR latency, audio underrun rates or full-session acceptance.

The single drainer now waits for enqueue/stop signals instead of polling every 10 ms. It clears the signal BEFORE checking the queue. Thus a push before clear is visible in the queue, while a push between empty pop and wait leaves the event set. Stop still closes ingress after capture's stop attempt, accepts its tail, drains accepted chunks and joins before downstream flush. Capacity, drop-oldest policy, callback ownership and failure/retry behavior are unchanged.

Offline validation passed 93 tests. New event/barrier tests cover idle signal waiting, both sides of clear/pop, coalesced signals with drop-oldest retention, nonblocking capture callback and 20 idle start/stop cycles. Removing enqueue signalling and moving clear after an empty pop each failed the forced race test. Existing stop-tail/flush/retry tests remain; three assertions about the producer's next statement running first were replaced with direct different-thread assertions, because OS scheduling provides no such relative-order guarantee.

The unchanged native capture/inference calls can still block shutdown if they do not return. This patch does not add cancellation to those libraries or claim real-device acceptance.
