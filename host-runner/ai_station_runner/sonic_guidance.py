"""Independent Sonic guidance branches; never split the temporal context."""


def install_guidance(unet, device_count):
    import torch

    if type(device_count) is not int or device_count not in {1, 2}:
        raise ValueError("Choose one or two explicitly allocated GPUs")
    native = unet.forward
    if device_count == 2:

        class GuidanceBatch(torch.nn.Module):
            def __init__(self, model):
                super().__init__()
                self.model = model

            def forward(self, sample, timesteps, clip, audio, time_ids, mask):
                # Calling the class method avoids recursing into our instance
                # adapter after DataParallel replicates it onto the other GPU.
                return type(self.model).forward(
                    self.model,
                    sample,
                    timesteps,
                    encoder_hidden_states=(clip.flatten(0, 1), [audio.flatten(0, 1)]),
                    added_time_ids=time_ids,
                    cross_attention_kwargs={"ip_adapter_masks": [mask[:1]]},
                    return_dict=False,
                )[0]

        parallel = torch.nn.DataParallel(GuidanceBatch(unet).eval(), device_ids=[0, 1], output_device=0)

    def forward(sample, timestep, encoder_hidden_states, added_time_ids, **kwargs):
        if (
            tuple(sample.shape[:2]) != (3, 25)
            or set(kwargs) != {"cross_attention_kwargs", "return_dict"}
            or kwargs["return_dict"] is not False
        ):
            raise ValueError("Sonic guidance/window contract changed")
        clip, audios = encoder_hidden_states
        masks = kwargs["cross_attention_kwargs"]
        if (
            len(audios) != 1
            or clip.shape[0] != 75
            or audios[0].shape[0] != 75
            or set(masks) != {"ip_adapter_masks"}
            or len(masks["ip_adapter_masks"]) != 1
            or masks["ip_adapter_masks"][0].shape[0] != 1
            or added_time_ids.shape[0] != 3
            or timestep.numel() != 1
        ):
            raise ValueError("Sonic conditioning/guidance contract changed")
        if device_count == 1:
            parts = []
            for branch in range(3):
                part = slice(branch, branch + 1)
                context = slice(branch * 25, (branch + 1) * 25)
                parts.append(
                    native(
                        sample[part],
                        timestep,
                        encoder_hidden_states=(clip[context], [audios[0][context]]),
                        added_time_ids=added_time_ids[part],
                        **kwargs,
                    )[0]
                )
            return (torch.cat(parts, dim=0),)
        # Flattened B*F conditioning must be reshaped BEFORE scattering B,
        # otherwise one GPU receives incomplete/different temporal context.
        result = parallel(
            sample,
            timestep.reshape(1).expand(3).contiguous(),
            clip.reshape(3, 25, *clip.shape[1:]),
            audios[0].reshape(3, 25, *audios[0].shape[1:]),
            added_time_ids,
            masks["ip_adapter_masks"][0].expand(3, *masks["ip_adapter_masks"][0].shape[1:]).contiguous(),
        )
        return (result,)

    unet.forward = forward
