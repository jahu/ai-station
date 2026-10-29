# Edit retains small source resolution

Actual UNIFIED-001 browser retesting correctly selected the previously inspected
attachment and changed the red square to yellow while retaining the blue circle.
The result still failed the complete request: its 384×256 source was enlarged to
1024×672 by treating Edit's default `max_side` as a target size.

Krea Edit now treats `max_side` as an upper bound. Sources smaller than that bound
are not automatically enlarged. Existing native minimum dimensions and 32-pixel
alignment remain; larger inputs are still bounded. Explicit width/height retain
their existing authority, and explicit smaller maximum sides still downscale.
Generate, Recompose, Upscale, input verification and model dispatch are unchanged.
This is not a promise of pixel-identical untouched regions or arbitrary native
resolutions unsupported by the adapter.

Tests cover the actual small-source dimensions, an existing portrait, bounded
large input, explicit output dimensions and a smaller maximum side through the
typed API, worker and synthetic native executor. They download the output and
verify its dimensions plus unchanged original bytes. Final acceptance requires
the actual same-conversation edit, downloaded image, visual inspection and QA row.
