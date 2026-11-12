"""Exercise the actual render loop with fake model/codec modules, without GPUs."""

import sys
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
from ai_station_runner.fish_job import render
from ai_station_runner.speech_chunks import text_chunks


class Codes:
    def __init__(self, marker):
        self.marker = marker

    def cpu(self):
        return self

    def to(self, _device):
        return self


class Device(str):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def runtime(monkeypatch, *, incomplete=False):
    calls = []
    seeds = []
    model = SimpleNamespace(
        config=SimpleNamespace(num_codebooks=1),
        tokenizer=SimpleNamespace(get_token_id=lambda _: 99),
        parameters=lambda: [SimpleNamespace(device="cuda:0")],
        setup_caches=lambda **_: None,
    )
    model.to = lambda **_: model
    model.eval = lambda: model
    codec = SimpleNamespace(parameters=lambda: [SimpleNamespace(device="cuda:1")], sample_rate=44100)
    cuda = SimpleNamespace(
        is_available=lambda: True,
        device_count=lambda: 2,
        device=lambda _: nullcontext(),
        is_bf16_supported=lambda: True,
        reset_peak_memory_stats=lambda _: None,
        mem_get_info=lambda _: (100 * 1024**3, 100 * 1024**3),
        max_memory_allocated=lambda _: 0,
    )
    torch = SimpleNamespace(
        cuda=cuda,
        device=Device,
        bfloat16="bf16",
        inference_mode=nullcontext,
        manual_seed=seeds.append,
        cat=lambda values, dim: values[0],
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(
        sys.modules, "soundfile", SimpleNamespace(write=lambda path, *a, **k: path.write_bytes(b"test PCM"))
    )
    for name in (
        "fish_speech",
        "fish_speech.models",
        "fish_speech.models.text2semantic",
        "fish_speech.models.text2semantic.inference",
        "fish_speech.models.text2semantic.llama",
        "fish_speech.tokenizer",
    ):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))

    def generate(**kwargs):
        calls.append(kwargs)
        if not incomplete:
            kwargs["decode_one_token"]()
        yield SimpleNamespace(action="sample", codes=Codes(len(calls)))

    samples = np.full(4410, 0.1)
    audio = SimpleNamespace(float=lambda: SimpleNamespace(cpu=lambda: SimpleNamespace(numpy=lambda: samples)))
    inference = sys.modules["fish_speech.models.text2semantic.inference"]
    inference.generate_long = generate
    inference.decode_one_token_ar = lambda: np.array([99, 0])
    inference.encode_audio = lambda *a: Codes("original recording")
    inference.decode_to_audio = lambda *a: audio
    inference.load_codec_model = lambda *a: codec
    sys.modules["fish_speech.models.text2semantic.llama"].DualARTransformer = SimpleNamespace(
        from_pretrained=lambda *a, **k: model
    )
    sys.modules["fish_speech.tokenizer"].IM_END_TOKEN = "EOS"
    return calls, seeds


@pytest.mark.parametrize("reference", [False, True])
def test_every_later_chunk_uses_one_fixed_voice_anchor_and_its_matching_text(
    tmp_path, monkeypatch, reference
):
    calls, seeds = runtime(monkeypatch)
    text = "[curious] Look at the changing light. " * 19
    chunks = text_chunks(text)
    assert len(chunks) >= 3
    request = SimpleNamespace(
        text=text,
        reference_text="Words in the recording" if reference else None,
        direction="natural",
        pace="natural",
        deadline_at=float("inf"),
    )
    report = render(
        request,
        runtime=tmp_path,
        models=tmp_path,
        work=tmp_path,
        reference=tmp_path / "reference.wav" if reference else None,
    )
    assert len(calls) == len(report["parts"]) == len(chunks)
    assert seeds == [42] * len(chunks)
    assert [c["text"] for c in calls] == chunks
    if reference:
        assert all(c["prompt_tokens"][0].marker == "original recording" for c in calls)
        assert all(c["prompt_text"] == ["Words in the recording"] for c in calls)
        assert report["voice_continuity"] == "provided_reference"
    else:
        assert calls[0]["prompt_text"] is calls[0]["prompt_tokens"] is None
        anchor = calls[1]["prompt_tokens"][0]
        assert anchor.marker == 1
        assert all(c["prompt_tokens"][0] is anchor for c in calls[1:])
        assert all(c["prompt_text"] == [chunks[0]] for c in calls[1:])
        assert report["voice_continuity"] == "first_generated_chunk"
    assert all(p["eos"] and p["samples"] == 4410 for p in report["parts"])


def test_incomplete_first_chunk_cannot_become_a_voice_reference_or_start_another_call(tmp_path, monkeypatch):
    calls, _ = runtime(monkeypatch, incomplete=True)
    request = SimpleNamespace(
        text="A complete spoken thought. " * 20,
        reference_text=None,
        direction="natural",
        pace="natural",
        deadline_at=float("inf"),
    )
    with pytest.raises(ValueError, match="partial audio"):
        render(request, runtime=tmp_path, models=tmp_path, work=tmp_path, reference=None)
    assert len(calls) == 1
    assert not list(tmp_path.glob("part-*.wav"))
