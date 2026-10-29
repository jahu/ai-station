# Explain rejected private page requests

WEB-007 safely refused a loopback URL but displayed a misleading search-topic
resolution error. A blocked explicit page read fell through to search rewriting
because the public URL extractor returned no usable targets.

Freeze a clear public-page error for explicit HTTP(S) reading targets rejected
by the existing public URL policy, including a quoted target. Do this before
search fallback, page fetch, rendering or answer inference. A mixed public/private
request fails as a whole rather than silently reading only one target. The error
does not echo credentials or addresses. Web-off requests and quoted/code examples
retain their existing behavior; no new page access is granted.

Existing DNS/address pinning, redirect checks and network permissions remain
unchanged. Tests exercise conversation enqueue/worker/message delivery with zero
search, fetch or inference calls for private targets and unsupported ports.
Actual acceptance still requires the original loopback request in the browser,
visible denial and inspection of its recorded execution.
