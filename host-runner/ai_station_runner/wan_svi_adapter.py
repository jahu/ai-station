"""Fixed Pro PEFT bridge for the pinned 14B GGUF loader; no custom graph API."""

RANK = 128
SUFFIXES = (".lora_A.default.weight", ".lora_B.default.weight")
TARGETS = frozenset(
    f"blocks.{block}.{layer}"
    for block in range(40)
    for layer in (
        "self_attn.q",
        "self_attn.k",
        "self_attn.v",
        "self_attn.o",
        "cross_attn.q",
        "cross_attn.k",
        "cross_attn.v",
        "cross_attn.o",
        "ffn.0",
        "ffn.2",
    )
)


def target_map(weights, shape_for):
    """Bind every fixed adapter matrix to its *logical* base-weight geometry.

    GGUF state_dict entries can contain packed meta tensors, so their dimensions
    cannot validate a LoRA. The caller must inspect the actual model parameter.
    """
    if set(weights) != {layer + suffix for layer in TARGETS for suffix in SUFFIXES}:
        raise ValueError("The fixed SVI Pro PEFT target layout changed")
    mapping = {}
    for layer in sorted(TARGETS):
        key = "diffusion_model." + layer + ".weight"
        shape = tuple(shape_for(key))
        if (
            len(shape) != 2
            or any(type(value) is not int or value <= 0 for value in shape)
            or tuple(weights[layer + SUFFIXES[0]].shape) != (RANK, shape[1])
            or tuple(weights[layer + SUFFIXES[1]].shape) != (shape[0], RANK)
        ):
            raise ValueError("The SVI Pro rank or logical target geometry changed")
        mapping[layer] = key
    return mapping


def attach(model, path):
    """Apply the verified Pro adapter at its fixed strength without weight rewrite.

    Native dispatch remains responsible for owned canonical paths, complete
    SHA-256 identity and correct high/low expert pairing before entering here.
    """
    import comfy.lora
    import comfy.utils

    if (
        path.suffix != ".safetensors"
        or model.model.latent_format.latent_channels != 16
        or len(model.model.diffusion_model.blocks) != 40
    ):
        raise ValueError("SVI Pro requires its fixed Wan21 14B model and SafeTensors adapter")
    weights = comfy.utils.load_torch_file(str(path), safe_load=True)

    def shape_for(key):
        parameter = comfy.utils.get_attr(model.model, key)
        return getattr(parameter, "tensor_shape", parameter.shape)

    mapping = target_map(weights, shape_for)
    patches = comfy.lora.load_lora(weights, mapping)
    if set(patches) != set(mapping.values()):
        raise ValueError("Not every SVI Pro target was mapped")
    result = model.clone()
    matched = result.add_patches(patches, 1.0)
    if set(matched) != set(mapping.values()):
        raise ValueError("Not every SVI Pro patch was attached")
    return result, {"tensor_keys": len(weights), "target_count": len(matched), "rank": RANK, "strength": 1.0}
