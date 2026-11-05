"""Closed graph admission rejects external/custom execution and permits new weights."""

import numpy as np
import onnx
import pytest
from app import embedding_graph
from onnx import TensorProto, helper, numpy_helper
from test_hub_embedding_installation import encoder as encoder


@pytest.mark.parametrize("change", ["domain", "external", "shape", "attribute", "function"])
def test_changed_or_executable_graph_is_not_a_supported_encoder(encoder, monkeypatch, change):
    path = encoder["reference_path"]
    model = onnx.load(path, load_external_data=False)
    if change == "domain":
        model.graph.node[0].domain = "untrusted.custom"
    elif change == "external":
        value = model.graph.initializer[0]
        value.data_location = TensorProto.EXTERNAL
        value.external_data.add(key="location", value="../../private-secret")
        monkeypatch.setattr(
            onnx,
            "load_external_data_for_model",
            lambda *args: pytest.fail("External data must never be read"),
        )
    elif change == "shape":
        model.graph.initializer[0].dims[0] = 9
    elif change == "function":
        model.functions.append(helper.make_function("custom", "Danger", [], [], [], []))
    else:
        model.graph.node[0].attribute.append(helper.make_attribute("axis", 1))
    path.write_bytes(model.SerializeToString())
    with pytest.raises(ValueError):
        embedding_graph.inspect(path)


def test_new_tensor_values_keep_the_supported_architecture_but_are_not_quality_qualification(encoder):
    path = encoder["reference_path"]
    model = onnx.load(path, load_external_data=False)
    model.graph.initializer[0].CopyFrom(
        numpy_helper.from_array(np.full((10, 384), 2, dtype=np.float32), name="weights")
    )
    path.write_bytes(model.SerializeToString())
    result = embedding_graph.inspect(path)
    assert result["schema_sha256"] == encoder["profile"]["schema_sha256"]
    assert result["runtime_qualified"] is False
