"""SDK-side offline preparation probe. Does not use a GPU or load speech weights."""

import hashlib
import importlib.metadata
import json
import socket
import sys
from pathlib import Path


def denied(*args, **kwargs):
    raise RuntimeError("Speech preparation probe cannot access the network")


def main():
    socket.socket.connect = denied
    socket.create_connection = denied
    folder = Path(sys.argv[1])
    import perth
    from chatterbox.models.tokenizers.tokenizer import MTLTokenizer
    from chatterbox.mtl_tts import _resolve_multilingual_t3_model

    if _resolve_multilingual_t3_model("v3") != "t3_mtl23ls_v3.safetensors":
        raise RuntimeError("The speech SDK does not implement the qualified v3 loader")
    if importlib.metadata.version("resemble-perth") != "1.1.0":
        raise RuntimeError("The real pinned Perth implementation is required")
    weight = Path(perth.__file__).parent / "perth_net/pretrained/implicit/perth_net_250000.pth.tar"
    if (
        hashlib.sha256(weight.read_bytes()).hexdigest()
        != "a15bce457ebc53ce5e6c9c3f11df78cf7ee2bf9cdab0a798902135b4c4027670"
    ):
        raise RuntimeError("The speech SDK omitted or changed the bundled watermark model")
    tokenizer = MTLTokenizer(str(folder / "models/grapheme_mtl_merged_expanded_v1.json"))
    converter = tokenizer.cangjie_converter
    if not converter.word2cj or converter.segmenter is None:
        raise RuntimeError("The complete offline tokenizer assets are required")
    (folder / "probe.json").write_text(
        json.dumps(
            {
                "v3_loader": True,
                "perth_weight_verified": True,
                "offline_chinese_mapping": True,
                "offline_segmenter": True,
                "network_disabled_in_probe": True,
                "gpu_used": False,
            }
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
