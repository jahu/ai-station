"""General Artifact adoption for bounded native temporal conditioning."""


class MotionArtifacts:
    motion_role = "wan_motion"
    motion_filename = "wan-motion.safetensors"

    def output_metadata(self, output):
        import json
        from pathlib import PurePosixPath

        from app.config import get_settings
        from app.paths import safe_join

        report = safe_join(get_settings().data_dir, str(PurePosixPath(output).with_suffix(".json")))
        if not report.is_file():
            return {}
        if report.stat().st_size > 8192:
            raise ValueError("Native video report exceeds its bounded metadata budget")
        values = json.loads(report.read_text())
        if not isinstance(values, dict):
            raise ValueError("Native motion metadata must be an object")
        return values

    def on_success(self, session, run, artifact):
        motion = artifact.metadata_json.get("motion_context")
        if motion:
            from app.artifacts import adopt_existing

            context = adopt_existing(
                session,
                relative_path=motion["relative_path"],
                artifact_type="document",
                mime_type="application/octet-stream",
                original_filename=self.motion_filename,
                run_id=run.id,
                parent_artifact_ids=[artifact.id],
                metadata={"internal_media": True, "role": self.motion_role, "context_frames": 17},
            )
            if context.sha256 != motion["sha256"] or context.size_bytes != motion["size_bytes"]:
                raise ValueError("Native motion checkpoint observation changed")
            artifact.metadata_json = {**artifact.metadata_json, "motion_context_artifact_id": context.id}
