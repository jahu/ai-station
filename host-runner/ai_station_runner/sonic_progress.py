"""Owned, atomic progress observations; never authorize final publication."""

import json


class Progress:
    def __init__(self, work, run_id, recipe, base_frames):
        self.path = work / "progress.json"
        self.run_id, self.recipe = run_id, recipe
        self.windows_per_step = (base_frames + 24) // 25
        self.total = self.windows_per_step * 25
        self.completed = 0
        self.write("preparing")

    def write(self, phase):
        value = {
            "version": 1,
            "run_id": self.run_id,
            "recipe": self.recipe,
            "phase": phase,
            "completed_windows": self.completed,
            "total_windows": self.total,
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, sort_keys=True))
        temporary.chmod(0o600)
        temporary.replace(self.path)

    def advance(self, pipeline, index, timestep, values):
        if self.completed >= self.total or index != self.completed // self.windows_per_step:
            raise ValueError("Sonic progress differs from its frozen global timeline")
        self.completed += 1
        self.write("animating")
        return values

    def finishing(self):
        if self.completed != self.total:
            raise ValueError("Sonic did not complete every global generation window")
        self.write("finishing")
