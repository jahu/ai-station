# Media resource waiting must not hide interactive work

A focused regression reproduces the problem: with a held GPU and eighteen
independent shot Runs, the next worker tick claims another older GPU-blocked shot
instead of a newly queued CPU task. The current five-second worker heartbeat can
turn that ordering into a long conversational delay. This is a verified claim
ordering failure, not a measured production latency benchmark.

After a selected shot observes unavailable GPU/RAM, defer only WAN attempts in
that same Task for two worker heartbeats. Store a server-authored UTC deadline
outside the immutable media plan. Both candidate selection and atomic claim must
respect it. CPU work (including composition) and other Tasks remain eligible.
No GPU/RAM reservation, permission or executor retry scope is expanded.

Release the deferral when a selected shot reaches a terminal state, and reset it
for an explicit media resume. Serialize metadata changes with Task Stop so the
stop marker cannot be lost; a stopped shot must not escape by being requeued.
Cooldown expiry remains a bounded recovery fallback after a worker crash.

Verify the original failing ordering test, immediate progress after owned capacity
is freed, same-Task CPU eligibility, expiry and claim guards, and Stop during a
resource-rejection race. Re-run existing parallel/serial, stop/resume, worker lease
and atomic-claim tests plus full checks. Frontend and Native source remain
unchanged; reuse their reviewed validation and avoid unrelated GPU inference.
