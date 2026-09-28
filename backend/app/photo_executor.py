"""Adapter around the existing photo pipeline's typed Runner operation."""

from app.host_media_executor import HostMediaExecutor


class PhotoPipeExecutor(HostMediaExecutor):
    name = "photo_pipe"
    suffix = ".png"
    artifact_type = "image"
    mime_type = "image/png"

    def _start(self, runner, run, allocated, output):
        payload = {
            key: run.parameters.get(key)
            for key in (
                "mode",
                "backend",
                "prompt",
                "negative",
                "edit_prompt",
                "width",
                "height",
                "steps",
                "cfg",
                "seed",
                "max_side",
                "repeats",
                "inputs",
            )
        }
        payload.update(run_id=run.id, gpu=allocated, output_relative=output)
        return runner.start_photo(payload)
