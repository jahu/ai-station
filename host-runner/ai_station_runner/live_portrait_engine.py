"""Fixed LivePortrait renderer: camera pixels are motion input, never output layers."""

import sys
from pathlib import Path

from ai_station_runner.live_face_engine import FaceEngine, FaceTrackingError


class PortraitEngine(FaceEngine):
    def __init__(self, detector: Path, models: dict, sdk: Path, *, gpu: int):
        import cv2
        import numpy as np
        import torch
        import yaml

        self.cv, self.np, self.torch = cv2, np, torch
        cv2.setNumThreads(1)
        torch.set_num_threads(2)
        self.device = torch.device("cuda", gpu)
        if not torch.cuda.is_available():
            raise RuntimeError("Animated portrait requires its allocated CUDA GPU")
        # This is the reviewed, immutable SDK snapshot, not an input-selected module.
        sys.path.insert(0, str(sdk))
        from src.modules.appearance_feature_extractor import AppearanceFeatureExtractor
        from src.modules.motion_extractor import MotionExtractor
        from src.modules.spade_generator import SPADEDecoder
        from src.modules.stitching_retargeting_network import StitchingRetargetingNetwork
        from src.modules.warping_network import WarpingNetwork
        from src.utils.camera import get_rotation_matrix, headpose_pred_to_degree

        self.rotation = get_rotation_matrix
        self.angle = headpose_pred_to_degree
        config = yaml.safe_load((sdk / "src/config/models.yaml").read_text())["model_params"]
        self.networks = {}
        for name, constructor, parameters in (
            (
                "appearance_feature_extractor",
                AppearanceFeatureExtractor,
                "appearance_feature_extractor_params",
            ),
            ("motion_extractor", MotionExtractor, "motion_extractor_params"),
            ("warping_module", WarpingNetwork, "warping_module_params"),
            ("spade_generator", SPADEDecoder, "spade_generator_params"),
        ):
            model = constructor(**config[parameters])
            state = torch.load(models["portrait_" + name], map_location="cpu", weights_only=True)
            model.load_state_dict(state, strict=True)
            self.networks[name] = model.eval().to(self.device)
        state = torch.load(
            models["portrait_stitching_retargeting_module"], map_location="cpu", weights_only=True
        )
        stitch = StitchingRetargetingNetwork(**config["stitching_retargeting_module_params"]["stitching"])
        # Upstream checkpoints retain the DataParallel prefix for this submodule.
        stitch.load_state_dict(
            {key.removeprefix("module."): value for key, value in state["retarget_shoulder"].items()},
            strict=True,
        )
        self.networks["stitch"] = stitch.eval().to(self.device)
        self.detector = cv2.FaceDetectorYN.create(str(detector), "", (640, 480), 0.85, 0.3, 1000)
        self.reference = self.baseline = None
        self.driver_crop = None

    def _crop(self, frame, *, driving):
        self._check_image(frame)
        height, width = frame.shape[:2]
        factor = min(1.0, 640 / max(height, width))
        small = self.cv.resize(frame, (round(width * factor), round(height * factor)))
        self.detector.setInputSize((small.shape[1], small.shape[0]))
        _, found = self.detector.detect(small)
        if found is None or len(found) == 0:
            raise FaceTrackingError("No face tracked; animated portrait paused")
        if len(found) != 1:
            raise FaceTrackingError("More than one face; animated portrait paused")
        x, y, w, h = found[0, :4] / factor
        if not self.np.isfinite([x, y, w, h]).all() or min(w, h) < 20:
            raise FaceTrackingError("Unstable portrait tracking; output paused")
        # A head/shoulders crop keeps reference hair and skin, unlike the face mask.
        crop = self.np.array([x + w / 2, y + h * 0.4, max(w, h) * 2.3])
        if driving:
            if self.driver_crop is not None:
                crop = self.driver_crop * 0.65 + crop * 0.35
            self.driver_crop = crop
        center_x, center_y, side = crop
        scale = 256 / side
        matrix = self.np.array([[scale, 0, 128 - scale * center_x], [0, scale, 128 - scale * center_y]])
        return self.cv.warpAffine(frame, matrix, (256, 256), borderMode=self.cv.BORDER_REPLICATE)

    def _tensor(self, pixels):
        data = self.np.ascontiguousarray(pixels[:, :, ::-1].transpose(2, 0, 1))
        return self.torch.from_numpy(data).unsqueeze(0).to(self.device, dtype=self.torch.float32) / 255

    def _motion(self, tensor):
        info = self.networks["motion_extractor"](tensor)
        info = {key: value.float() for key, value in info.items()}
        for key in ("pitch", "yaw", "roll"):
            info[key] = self.angle(info[key])
        info["kp"] = info["kp"].reshape(1, 21, 3)
        info["exp"] = info["exp"].reshape(1, 21, 3)
        info["rotation"] = self.rotation(info["pitch"], info["yaw"], info["roll"])
        if not all(self.torch.isfinite(value).all() for value in info.values()):
            raise FaceTrackingError("Invalid portrait motion; output paused")
        return info

    def set_reference(self, image):
        tensor = self._tensor(self._crop(image, driving=False))
        with self.torch.inference_mode(), self.torch.autocast("cuda", dtype=self.torch.float16):
            motion = self._motion(tensor)
            self.features = self.networks["appearance_feature_extractor"](tensor).float()
            self.reference = motion
            self.source_points = (
                motion["scale"] * (motion["kp"] @ motion["rotation"] + motion["exp"])
                + motion["t"][:, None, :]
            )
        self.baseline = None
        self.driver_crop = None

    def transform(self, frame):
        if self.reference is None:
            raise ValueError("Choose a valid portrait reference first")
        tensor = self._tensor(self._crop(frame, driving=True))
        torch = self.torch
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
            driving = self._motion(tensor)
            if any(
                float(driving[k].abs().max()) > bound
                for k, bound in (("yaw", 65), ("pitch", 55), ("roll", 60))
            ):
                raise FaceTrackingError("Face turned too far; look toward the camera to resume")
            if self.baseline is None:
                self.baseline = {key: value.clone() for key, value in driving.items()}
            initial, source = self.baseline, self.reference
            rotation = driving["rotation"] @ initial["rotation"].transpose(1, 2) @ source["rotation"]
            expression = source["exp"] + driving["exp"] - initial["exp"]
            translation = source["t"] + driving["t"] - initial["t"]
            translation = translation.clone()
            translation[:, 2] = 0
            scale = source["scale"] * driving["scale"] / initial["scale"].clamp_min(1e-5)
            points = scale * (source["kp"] @ rotation + expression) + translation[:, None, :]
            delta = self.networks["stitch"](
                torch.cat((self.source_points.flatten(1), points.flatten(1)), dim=1)
            ).float()
            points = points + delta[:, :63].reshape(1, 21, 3)
            points[:, :, :2] += delta[:, 63:65].reshape(1, 1, 2)
            warped = self.networks["warping_module"](
                self.features, kp_driving=points, kp_source=self.source_points
            )
            output = self.networks["spade_generator"](warped["out"])
            if output.shape != (1, 3, 512, 512) or not torch.isfinite(output).all():
                raise RuntimeError("The portrait renderer returned invalid pixels")
            pixels = (output[0].float().clamp(0, 1).permute(1, 2, 0) * 255).byte().cpu().numpy()
        # Only the reference-conditioned renderer contributes pixels to this frame.
        return self.np.ascontiguousarray(pixels[:, :, ::-1])
