"""Model/mode-specific image controls, shared by planning and request binding."""

from copy import deepcopy

CONTROL_FIELDS = frozenset({"reference_layout"})
MODEL_FIT_POLICY = "model-fit-v3"
CURRENT_IMAGE_POLICIES = frozenset({"configured-default-v2", MODEL_FIT_POLICY})
REFERENCE_LAYOUT = {
    "type": "string",
    "enum": ["aligned", "beside"],
    "description": "Placement of every selected reference inside this model: aligned keeps framing; beside permits a new viewpoint/composition. No input is implicitly treated as a fixed scene. Neither option changes the number of output files.",
}


def control_schema(backend, mode):
    if backend == "krea2" and mode in {"img2img", "recompose"}:
        return {"reference_layout": deepcopy(REFERENCE_LAYOUT)}
    return {}


def validate_controls(backend, mode, controls, *, required=False):
    supported = control_schema(backend, mode)
    if controls.keys() - supported.keys():
        raise ValueError("Reference controls apply only to Krea2 Edit or Recompose")
    if required and supported and not controls:
        raise ValueError(
            "Choose reference_layout explicitly for this Krea2 reference operation: "
            "beside allows a different viewpoint or composition; aligned keeps reference framing. "
            "Use the requested visual change to decide, then retry the tool with that argument."
        )
    for name, value in controls.items():
        if value not in supported[name]["enum"]:
            raise ValueError("Unsupported " + name + " value for the selected image model")
