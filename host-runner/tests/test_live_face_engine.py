from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from ai_station_runner.live_face_engine import FaceEngine, FaceTrackingError


class Pixels:
    dtype = "uint8"
    shape = (480, 640, 3)
    ndim = 3


@pytest.fixture
def engine():
    # Optional inference dependencies stay out of the ordinary test environment.
    value = FaceEngine.__new__(FaceEngine)
    value.np = SimpleNamespace(ndarray=Pixels, uint8="uint8")
    value.cv = SimpleNamespace(resize=Mock(return_value=Pixels()))
    value.detector = SimpleNamespace(setInputSize=Mock(), detect=Mock(return_value=(None, None)))
    value.swapper = SimpleNamespace(run=Mock())
    value.identity = object()
    return value


def test_tracking_loss_never_returns_the_original_image(engine):
    with pytest.raises(FaceTrackingError, match="No face tracked"):
        engine.transform(Pixels())
    engine.swapper.run.assert_not_called()


def test_multiple_faces_never_silently_choose_another_person(engine):
    engine.detector.detect.return_value = (None, [object(), object()])
    with pytest.raises(FaceTrackingError, match="More than one face"):
        engine.transform(Pixels())
    engine.swapper.run.assert_not_called()


@pytest.mark.parametrize("shape", [(64, 63, 3), (1920, 1080, 3), (480, 640, 4), (1440, 1440, 3)])
def test_oversized_or_wrong_image_geometry_refuses_before_detection(engine, shape):
    pixels = Pixels()
    pixels.shape = shape
    with pytest.raises(ValueError, match="bounded BGR"):
        engine.transform(pixels)
    engine.detector.detect.assert_not_called()
    engine.swapper.run.assert_not_called()


def test_unprepared_reference_cannot_start_inference(engine):
    engine.identity = None
    with pytest.raises(ValueError, match="reference"):
        engine.transform(Pixels())
    engine.detector.detect.assert_not_called()
    engine.swapper.run.assert_not_called()
