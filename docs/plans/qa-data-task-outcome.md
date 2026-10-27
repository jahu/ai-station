# Data result status follows execution, not graph publication

Real UX-003 browser QA found a failed Task displaying a green “succeeded” data
card with “Preparing data analysis” and “View progress and Stop”. The card used
the latest filtered data Run, which could be the successful graph publisher.
Its failing model-load prerequisite was present only in the complete Task steps.

Pass the existing Task outcome and steps into the shared data result card. A
terminal failure/cancellation/interruption takes precedence over successful
preparation when no verified result exists, and execution details point to the
actual non-superseded terminal step. Publication alone is still preparing; an
otherwise finished Task without a verified result is explicitly unavailable.
Prefer the failing prerequisite outside the filtered data graph to its downstream
failure. Keep long native startup traces in execution details, with a short model
startup failure in the conversation.
Already verified results remain visible even when a later delivery/notification
step fails. No persisted Run state, recovery policy or retry authority changes.

Acceptance: reopen the original failed QA analysis in the actual conversation,
verify the failed badge and useful error with no endless preparing/Stop link,
and follow execution details to the real failed prerequisite. Successful and
repaired analyses must still show their real tables and downloads after reload.
