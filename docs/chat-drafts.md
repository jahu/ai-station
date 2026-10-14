# Chat draft text and retry identity

Unsent prompt text survives refresh and navigating between conversations in the
same browser tab. Entry and saved conversations have separate session drafts;
accepted Send clears its draft, while a network failure preserves it. Explicit
**New conversation** clears only the entry draft. Nothing is sent while typing.
If another prompt was typed while Send was being accepted, acceptance clears only
the submitted text and preserves that newer draft.

Drafts are bounded to the existing 32,000-character prompt limit and kept in
browser session storage, not long-term memory. Closing the browser session ends
that storage. Files, permissions and tool selections are not restored; the
composer explicitly asks to reattach files and confirm tools when text is restored.
Storage denial or quota exhaustion leaves an editable in-memory composer.

A pending turn also keeps a compact SHA-256 payload fingerprint and request UUID
in session storage. Retrying the exact same request after refresh reuses that
UUID, so the server's existing receipt returns the accepted Run. A different
payload or successful acceptance clears/replaces that identity. No attachment
bytes, credential or full serialized request is stored in this receipt cache.
Without browser Web Crypto/storage, the existing in-memory retry identity remains.

Tests cover conversation isolation, reload/remount, explicit New conversation,
successful clearing, denied storage and exact retry/new-intent identities. This
increment does not create new API execution paths or change model/permission policy.
