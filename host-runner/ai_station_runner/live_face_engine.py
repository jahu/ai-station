"""Worker-only ONNX face engine. Optional dependencies never enter the HTTP process.

A failed or ambiguous detection raises instead of returning an unswapped frame.
The live-session adapter must qualify and admit its fixed model files separately.
"""

from pathlib import Path


class FaceTrackingError(ValueError):
    """A transformed output cannot be safely produced for this frame."""


class FaceEngine:
    def __init__(self, detector: Path, recognizer: Path, swapper: Path, *, gpu: int):
        import cv2
        import numpy as np
        import onnx
        import onnxruntime as ort

        self.cv = cv2
        self.np = np
        cv2.setNumThreads(1)
        ort.preload_dlls(directory="")
        if "CUDAExecutionProvider" not in ort.get_available_providers():
            raise RuntimeError("The live face engine needs its qualified CUDA provider")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        providers = [
            (
                "CUDAExecutionProvider",
                {
                    "device_id": gpu,
                    "gpu_mem_limit": 1536 * 1024**2,
                    "cudnn_conv_algo_search": "HEURISTIC",
                    "arena_extend_strategy": "kSameAsRequested",
                },
            ),
            "CPUExecutionProvider",
        ]
        self.recognizer = ort.InferenceSession(str(recognizer), options, providers=providers)
        self.swapper = ort.InferenceSession(str(swapper), options, providers=providers)
        for session in (self.recognizer, self.swapper):
            session.disable_fallback()
            if session.get_providers()[0] != "CUDAExecutionProvider":
                raise RuntimeError("CUDA admission failed; CPU fallback is not a live qualification")
        if [(v.name, v.shape) for v in self.swapper.get_inputs()] != [
            ("target", [1, 3, 128, 128]),
            ("source", [1, 512]),
        ]:
            raise ValueError("The face checkpoint does not match the fixed live graph")
        graph = onnx.load(swapper, load_external_data=False)
        maps = [v for v in graph.graph.initializer if v.name == "initializer" and list(v.dims) == [512, 512]]
        if len(maps) != 1:
            raise ValueError("The face checkpoint has no unique identity projection")
        self.projection = onnx.numpy_helper.to_array(maps[0]).astype(np.float32)
        del graph
        self.detector = cv2.FaceDetectorYN.create(str(detector), "", (640, 480), 0.85, 0.3, 1000)
        self.template = np.array(
            [
                [38.2946, 51.6963],
                [73.5318, 51.5014],
                [56.0252, 71.7366],
                [41.5493, 92.3655],
                [70.7299, 92.2041],
            ],
            dtype=np.float32,
        )
        y, x = np.mgrid[:128, :128]
        mask = (((x - 63.5) / 54) ** 2 + ((y - 66) / 60) ** 2 <= 1).astype(np.float32)
        self.mask = cv2.GaussianBlur(mask, (17, 17), 0)
        self.identity = None

    def _check_image(self, frame):
        np = self.np
        if (
            not isinstance(frame, np.ndarray)
            or frame.dtype != np.uint8
            or frame.ndim != 3
            or frame.shape[2] != 3
            or not 64 <= frame.shape[0] <= 1440
            or not 64 <= frame.shape[1] <= 1440
            or frame.shape[0] * frame.shape[1] > 1440 * 960
        ):
            raise ValueError("Live face input must be a bounded BGR image")

    def _landmarks(self, frame):
        self._check_image(frame)
        height, width = frame.shape[:2]
        scale = min(1.0, 640 / max(height, width))
        small = self.cv.resize(frame, (round(width * scale), round(height * scale)))
        self.detector.setInputSize((small.shape[1], small.shape[0]))
        _, found = self.detector.detect(small)
        if found is None or len(found) == 0:
            raise FaceTrackingError("No face tracked; transformed output paused")
        if len(found) != 1:
            raise FaceTrackingError("More than one face; transformed output paused")
        return found[0, 4:14].reshape(5, 2) / scale

    def _align(self, landmarks, size):
        np = self.np
        destination = self.template + (8 if size == 128 else 0) * np.array([1, 0], np.float32)
        rows = []
        for x, y in landmarks:
            rows.extend([[x, -y, 1, 0], [y, x, 0, 1]])
        values, _, rank, _ = np.linalg.lstsq(np.asarray(rows), destination.reshape(-1), rcond=None)
        a, b, tx, ty = values
        if rank != 4 or not np.isfinite(values).all() or not 1e-5 < a * a + b * b < 100:
            raise FaceTrackingError("Unstable face alignment; transformed output paused")
        return np.array([[a, -b, tx], [b, a, ty]], dtype=np.float32)

    def set_reference(self, image):
        landmarks = self._landmarks(image)
        crop = self.cv.warpAffine(image, self._align(landmarks, 112), (112, 112))
        tensor = self.cv.dnn.blobFromImage(crop, 1 / 127.5, (112, 112), (127.5,) * 3, swapRB=True)
        embedding = self.recognizer.run(None, {self.recognizer.get_inputs()[0].name: tensor})[0]
        norm = self.np.linalg.norm(embedding)
        if not self.np.isfinite(embedding).all() or norm <= 0:
            raise ValueError("The reference identity could not be encoded")
        identity = (embedding / norm).astype(self.np.float32) @ self.projection
        norm = self.np.linalg.norm(identity)
        if not self.np.isfinite(identity).all() or norm <= 0:
            raise ValueError("The reference identity projection is invalid")
        self.identity = (identity / norm).astype(self.np.float32)

    def transform(self, frame):
        if self.identity is None:
            raise ValueError("Choose a valid face reference first")
        landmarks = self._landmarks(frame)
        matrix = self._align(landmarks, 128)
        crop = self.cv.warpAffine(frame, matrix, (128, 128))
        tensor = self.cv.dnn.blobFromImage(crop, 1 / 255, (128, 128), (0, 0, 0), swapRB=True)
        output = self.swapper.run(None, {"target": tensor, "source": self.identity})[0]
        if output.shape != (1, 3, 128, 128) or not self.np.isfinite(output).all():
            raise RuntimeError("The live face model returned invalid pixels")
        pixels = self.np.clip(output[0].transpose(1, 2, 0)[:, :, ::-1] * 255, 0, 255)
        inverse = self.cv.invertAffineTransform(matrix)
        size = (frame.shape[1], frame.shape[0])
        converted = self.cv.warpAffine(pixels, inverse, size)
        mask = self.cv.warpAffine(self.mask, inverse, size)[:, :, None]
        return self.np.clip(converted * mask + frame * (1 - mask), 0, 255).astype(self.np.uint8)
