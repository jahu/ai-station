# Complete long speech

The actual fresh 575-character Polish narration test on 2026-10-26 exposed a
truncated closing sentence. All twelve avatar windows and final composition used
the actual generated 30.32-second WAV correctly. CPU Whisper tiny recognized the
start of the closing sentence but no ending. Inspection of the installed
Chatterbox implementation confirmed `max_new_tokens=1000` in each generation.
The original script and installed runtime must remain unchanged.

Keep the typed 1000-character SpeechRequest and ordinary Task/Run lifecycle.
Short text retains the installed script's existing argv. Longer text uses a fixed
native wrapper: split at sentence/word boundaries into at most 220 characters,
invoke the same configured offline CLI sequentially in the owned process group,
validate intact compatible PCM parts and concatenate their real samples. Publish
the final WAV only when every part succeeds; never pad or repeat speech. Stop and
absolute deadlines continue to signal the entire owned group. Intermediate files
stay under the Run directory; callers cannot choose commands, paths or chunk size.

Verify a fake CLI that truncates a long individual invocation, exact sample/order
preservation, final-clause delivery, middle-part failure, incompatible/truncated
PCM rejection, no overwrite and cancellation while a child runs. Run backend/native
gates and qualify the same real text/reference through normal workers and a private
Runner, with CPU ASR of the actual output. Preserve the failed earlier receipt.
Only after speech fidelity is established, qualify its complete avatar output and
player. The earlier avatar remains evidence for composition/audio preservation,
not proof of complete requested narration. No schema or frontend change is needed.
