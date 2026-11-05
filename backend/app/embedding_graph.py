"""Closed ONNX encoder graphs, inspected without external data or custom execution."""

import hashlib
import json
from pathlib import Path

PROFILE = "e5-small-onnx-f32-v1"
MAX_MODEL_BYTES = 512 * 1024**2


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def descriptor(path):
    # Call only in an owned, offline, address-space/deadline-bounded CPU child.
    import onnx

    if not 0 < Path(path).stat().st_size <= MAX_MODEL_BYTES:
        raise ValueError("This encoder exceeds the bounded ONNX profile")
    model = onnx.load_model(path, format="protobuf", load_external_data=False)
    graph = model.graph
    if model.functions or model.training_info or graph.sparse_initializer or not 1 <= len(graph.node) <= 4096:
        raise ValueError("Only the fixed inference graph is admitted")
    if not 1 <= len(graph.initializer) <= 1024 or len({t.name for t in graph.initializer}) != len(
        graph.initializer
    ):
        raise ValueError("The encoder needs unique bounded embedded tensors")
    if any(v.domain or not 1 <= v.version <= 21 for v in model.opset_import):
        raise ValueError("Custom ONNX operator domains are not admitted")

    def tensor(value):
        if value.external_data or value.data_location != onnx.TensorProto.DEFAULT or value.string_data:
            raise ValueError("External or executable tensor sources are not admitted")
        if (
            value.data_type not in {1, 2, 3, 6, 7, 9, 10}
            or len(value.dims) > 6
            or any(not 0 < d <= 1_000_000 for d in value.dims)
        ):
            raise ValueError("The encoder tensor dimensions are invalid")
        return {"name": value.name, "dtype": value.data_type, "shape": list(value.dims)}

    tensors = [tensor(value) for value in graph.initializer]
    nodes = []
    for node in graph.node:
        if node.domain or node.op_type in {"If", "Loop", "Scan"} or len(node.attribute) > 32:
            raise ValueError("Custom or nested ONNX execution is not admitted")
        attributes = []
        for attribute in node.attribute:
            if attribute.type in {
                onnx.AttributeProto.GRAPH,
                onnx.AttributeProto.GRAPHS,
                onnx.AttributeProto.SPARSE_TENSOR,
                onnx.AttributeProto.SPARSE_TENSORS,
            }:
                raise ValueError("Nested graphs and external sparse tensors are not admitted")
            if attribute.type == onnx.AttributeProto.TENSOR:
                tensor(attribute.t)
            if attribute.type == onnx.AttributeProto.TENSORS:
                for value in attribute.tensors:
                    tensor(value)
            if attribute.ByteSize() > 1024**2:
                raise ValueError("Encoder operator attributes exceed the fixed profile")
            attributes.append(
                [attribute.name, hashlib.sha256(attribute.SerializeToString(deterministic=True)).hexdigest()]
            )
        nodes.append(
            {
                "op": node.op_type,
                "inputs": list(node.input),
                "outputs": list(node.output),
                "attributes": sorted(attributes),
            }
        )
    schema = {
        "ir_version": model.ir_version,
        "opsets": [[value.domain, value.version] for value in model.opset_import],
        "inputs": [value.SerializeToString(deterministic=True).hex() for value in graph.input],
        "outputs": [value.SerializeToString(deterministic=True).hex() for value in graph.output],
        "tensors": sorted(tensors, key=lambda value: value["name"]),
        "nodes": nodes,
    }
    return {
        "schema_sha256": fingerprint(schema),
        "tensor_count": len(tensors),
        "node_count": len(nodes),
        "input_names": [value.name for value in graph.input],
        "output_names": [value.name for value in graph.output],
        "dtypes": sorted({value["dtype"] for value in tensors}),
    }


def inspect(path, profile=PROFILE):
    expected = recipe(profile)
    observed = descriptor(path)
    if any(
        observed.get(key) != expected[key]
        for key in ("schema_sha256", "tensor_count", "node_count", "input_names", "output_names", "dtypes")
    ):
        raise ValueError("The ONNX graph needs its own qualified encoder profile")
    return {**observed, "profile": PROFILE, "source": "onnx_embedded_graph", "runtime_qualified": False}


def recipe(profile=PROFILE):
    if profile != PROFILE:
        raise ValueError("Unknown memory encoder profile")
    return json.loads(Path(__file__).with_name("recipes").joinpath(PROFILE + ".json").read_text())
