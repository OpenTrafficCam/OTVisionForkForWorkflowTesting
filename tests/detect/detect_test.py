import bz2
import copy
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import validate

import OTVision.config as config
from OTVision.config import DEFAULT_EXPECTED_DURATION
from OTVision.dataformat import (
    CLASS,
    CONFIDENCE,
    DATA,
    DETECTION,
    DETECTIONS,
    METADATA,
    OCCURRENCE,
    OTDET_VERSION,
    OTVISION_VERSION,
    H,
    W,
    X,
    Y,
)
from OTVision.detect.detect import Timestamper
from OTVision.detect.detect import main as detect
from OTVision.detect.yolo import Yolov8, loadmodel
from tests.conftest import YieldFixture

CAR = "car"
TRUCK = "truck"
PERSON = "person"
BICYCLE = "bicycle"

otdet_schema = {
    "type": "object",
    "properties": {
        "metadata": {
            "type": "object",
            "properties": {
                "vid": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string"},
                        "filetype": {"type": "string"},
                        "width": {"type": "number"},
                        "height": {"type": "number"},
                        "fps": {"type": "number"},
                        "frames": {"type": "number"},
                    },
                },
                "det": {
                    "type": "object",
                    "properties": {
                        "detector": {"type": "string"},
                        "weights": {"type": "string"},
                        "conf": {"type": "number"},
                        "iou": {"type": "number"},
                        "size": {"type": "number"},
                        "chunksize": {"type": "number"},
                        "normalized": {"type": "boolean"},
                    },
                },
            },
        }
    },
    "data": {
        "type": "object",
        "properties": {
            "propertyNames": {"pattern": "[1-9][0-9]*"},
            "properties": {
                "classified": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "class": "string",
                            "conf": "number",
                            "x": "number",
                            "y": "number",
                            "w": "number",
                            "h": "number",
                        },
                    },
                }
            },
        },
    },
}


@dataclass
class Detection:
    det_class: str
    conf: float
    x: float
    y: float
    w: float
    h: float

    @staticmethod
    def from_dict(d: dict) -> "Detection":
        return Detection(d[CLASS], d[CONFIDENCE], d[X], d[Y], d[W], d[H])

    def is_normalized(self) -> bool:
        return (
            (self.w >= 0 and self.w < 1)
            and (self.y >= 0 and self.y < 1)
            and (self.w >= 0 and self.w < 1)
            and (self.h >= 0 and self.h < 1)
        )


@dataclass
class Frame:
    number: int
    detections: list[Detection]

    @staticmethod
    def from_dict(frame_number: str, d: dict) -> "Frame":
        detections = [Detection.from_dict(detection) for detection in d[DETECTIONS]]
        return Frame(int(frame_number), detections)


def read_bz2_otdet(otdet: Path) -> dict:
    with bz2.open(otdet, "r") as file:
        result_otdet_json = json.load(file)
    return result_otdet_json


def remove_ignored_metadata(data: dict) -> dict:
    data[OTDET_VERSION] = "ignored"
    data[DETECTION][OTVISION_VERSION] = "ignored"
    return data


def count_classes(frames: list[Frame]) -> dict:
    class_counts: dict[str, int] = {}
    for frame in frames:
        for det in frame.detections:
            if det.det_class in class_counts.keys():
                class_counts[det.det_class] += 1
            else:
                class_counts[det.det_class] = 0
    return class_counts


@pytest.fixture(scope="module")
def detect_test_data_dir(test_data_dir: Path) -> Path:
    return test_data_dir / "detect"


@pytest.fixture(scope="module")
def detect_test_tmp_dir(test_data_tmp_dir: Path) -> YieldFixture[Path]:
    detect_tmp_dir = test_data_tmp_dir / "detect"
    detect_tmp_dir.mkdir(exist_ok=True)
    yield detect_tmp_dir
    shutil.rmtree(detect_tmp_dir)


@pytest.fixture(scope="module")
def cyclist_mp4(detect_test_data_dir: Path, detect_test_tmp_dir: Path) -> Path:
    fname = "Testvideo_Cars-Cyclist_FR20_2020-01-01_00-00-00.mp4"
    src = detect_test_data_dir / fname
    dest = detect_test_tmp_dir / fname
    shutil.copy2(src, dest)
    return dest


@pytest.fixture(scope="module")
def truck_mp4(detect_test_data_dir: Path, detect_test_tmp_dir: Path) -> Path:
    fname = "Testvideo_Cars-Truck_FR20_2020-01-01_00-00-00.mp4"
    src = detect_test_data_dir / fname
    dest = detect_test_tmp_dir / fname
    shutil.copy2(src, dest)
    return dest


@pytest.fixture(scope="module")
def default_cyclist_otdet(detect_test_data_dir: Path) -> Path:
    fname = "Testvideo_Cars-Cyclist_FR20_2020-01-01_00-00-00.otdet"
    return detect_test_data_dir / "default" / fname


@pytest.fixture(scope="session")
def yolov8m() -> Yolov8:
    return loadmodel(
        weights="yolov8m",
        confidence=0.25,
        iou=0.45,
        img_size=640,
        half_precision=False,
        normalized=False,
    )


class TestDetect:
    conf: float = 0.25
    filetypes: list[str] = config.CONFIG[config.FILETYPES][config.VID]

    @pytest.fixture(scope="class")
    def result_cyclist_otdet(
        self, yolov8m: Yolov8, cyclist_mp4: Path, detect_test_tmp_dir: Path
    ) -> Path:
        detect(
            paths=[cyclist_mp4],
            model=yolov8m,
            expected_duration=DEFAULT_EXPECTED_DURATION,
        )

        return detect_test_tmp_dir / f"{cyclist_mp4.stem}.otdet"

    def test_detect_emptyDirAsParam(
        self, yolov8m: Yolov8, detect_test_tmp_dir: Path
    ) -> None:
        empty_dir = detect_test_tmp_dir / "empty"
        empty_dir.mkdir()
        with pytest.raises(
            FileNotFoundError, match=r"No videos of type .* found to detect!"
        ):
            detect(
                paths=[empty_dir],
                model=yolov8m,
                expected_duration=DEFAULT_EXPECTED_DURATION,
            )

    def test_detect_emptyListAsParam(self, yolov8m: Yolov8) -> None:
        with pytest.raises(
            FileNotFoundError, match=r"No videos of type .* found to detect!"
        ):
            detect(model=yolov8m, paths=[], expected_duration=DEFAULT_EXPECTED_DURATION)

    def test_detect_create_otdet(self, result_cyclist_otdet: Path) -> None:
        assert result_cyclist_otdet.exists()

    def test_detect_otdet_valid_json(self, result_cyclist_otdet: Path) -> None:
        try:
            otdet_file = bz2.open(str(result_cyclist_otdet), "r")
            json.load(otdet_file)
        finally:
            otdet_file.close()

    def test_detect_otdet_matches_schema(self, result_cyclist_otdet: Path) -> None:
        assert result_cyclist_otdet.exists()

        result_cyclist_otdet_json = read_bz2_otdet(result_cyclist_otdet)
        assert result_cyclist_otdet
        validate(result_cyclist_otdet_json, otdet_schema)

    def test_detect_metadata_matches(
        self, result_cyclist_otdet: Path, default_cyclist_otdet: Path
    ) -> None:
        result_cyclist_metadata = remove_ignored_metadata(
            read_bz2_otdet(result_cyclist_otdet)[METADATA]
        )
        expected_cyclist_metadata = remove_ignored_metadata(
            read_bz2_otdet(default_cyclist_otdet)[METADATA]
        )
        assert result_cyclist_metadata == expected_cyclist_metadata

    def test_detect_error_raised_on_wrong_filetype(
        self, yolov8m: Yolov8, detect_test_tmp_dir: Path
    ) -> None:
        video_path = detect_test_tmp_dir / "video.vid"
        video_path.touch()
        with pytest.raises(
            FileNotFoundError, match=r"No videos of type .* found to detect!"
        ):
            detect(
                paths=[video_path],
                model=yolov8m,
                expected_duration=DEFAULT_EXPECTED_DURATION,
            )

    def test_detect_bboxes_normalized(self, yolov8m: Yolov8, truck_mp4: Path) -> None:
        otdet_file = truck_mp4.parent / truck_mp4.with_suffix(".otdet")
        otdet_file.unlink(missing_ok=True)
        yolov8m.confidence = 0.25
        yolov8m.normalized = True
        detect(
            paths=[truck_mp4],
            model=yolov8m,
            expected_duration=DEFAULT_EXPECTED_DURATION,
        )
        otdet_dict = read_bz2_otdet(otdet_file)

        detections = [
            Frame.from_dict(number, det) for number, det in otdet_dict[DATA].items()
        ]
        for det in detections:
            for bbox in det.detections:
                assert bbox.is_normalized()
                assert bbox.conf >= self.conf
        otdet_file.unlink()

    def test_detect_bboxes_denormalized(self, yolov8m: Yolov8, truck_mp4: Path) -> None:
        otdet_file = truck_mp4.parent / truck_mp4.with_suffix(".otdet")
        otdet_file.unlink(missing_ok=True)
        yolov8m.normalized = False
        detect(
            model=yolov8m,
            paths=[truck_mp4],
            expected_duration=DEFAULT_EXPECTED_DURATION,
        )
        otdet_dict = read_bz2_otdet(otdet_file)

        frames = [
            Frame.from_dict(number, det) for number, det in otdet_dict[DATA].items()
        ]
        denormalized_bbox_found = False
        for frame in frames:
            for det in frame.detections:
                denormalized_bbox_found = (
                    denormalized_bbox_found or not det.is_normalized()
                )
                assert det.conf >= self.conf
        assert denormalized_bbox_found
        otdet_file.unlink()

    @pytest.mark.parametrize("conf", [0.0, 0.1, 0.5, 0.9, 1.0])
    def test_detect_conf_bbox_above_thresh(
        self, yolov8m: Yolov8, truck_mp4: Path, conf: float
    ) -> None:
        otdet_file = truck_mp4.parent / truck_mp4.with_suffix(".otdet")
        otdet_file.unlink(missing_ok=True)
        yolov8m.confidence = conf
        detect(
            paths=[truck_mp4],
            model=yolov8m,
            expected_duration=DEFAULT_EXPECTED_DURATION,
        )
        otdet_dict = read_bz2_otdet(otdet_file)

        detections = [
            Frame.from_dict(number, det) for number, det in otdet_dict[DATA].items()
        ]
        for det in detections:
            for bbox in det.detections:
                assert bbox.conf >= conf
        otdet_file.unlink()

    @pytest.mark.parametrize("overwrite", [(True), (False)])
    def test_detect_overwrite(
        self, yolov8m: Yolov8, truck_mp4: Path, overwrite: bool
    ) -> None:
        otdet_file = truck_mp4.parent / truck_mp4.with_suffix(".otdet")
        otdet_file.unlink(missing_ok=True)
        detect(
            paths=[truck_mp4],
            model=yolov8m,
            expected_duration=DEFAULT_EXPECTED_DURATION,
            overwrite=True,
        )

        first_mtime = otdet_file.stat().st_mtime_ns
        detect(
            paths=[truck_mp4],
            model=yolov8m,
            expected_duration=DEFAULT_EXPECTED_DURATION,
            overwrite=overwrite,
        )
        second_mtime = otdet_file.stat().st_mtime_ns

        if overwrite:
            assert first_mtime != second_mtime
        else:
            assert first_mtime == second_mtime
        otdet_file.unlink()

    def test_detect_fulfill_minimum_detection_requirements(
        self, yolov8m: Yolov8, cyclist_mp4: Path
    ) -> None:
        deviation = 0.2
        yolov8m.confidence = 0.5
        detect(
            paths=[cyclist_mp4],
            model=yolov8m,
            expected_duration=DEFAULT_EXPECTED_DURATION,
        )
        result_otdet = cyclist_mp4.parent / cyclist_mp4.with_suffix(".otdet")
        otdet_dict = read_bz2_otdet(result_otdet)

        frames = [
            Frame.from_dict(number, det) for number, det in otdet_dict[DATA].items()
        ]
        class_counts = count_classes(frames)
        assert class_counts[CAR] >= 120 * (1 - deviation)
        # not able to detect any trucks at conf_thresh=0.5
        # assert class_counts[TRUCK] >= 60 * (1 - deviation)
        assert class_counts[PERSON] >= 120 * (1 - deviation)
        assert class_counts[BICYCLE] >= 60 * (1 - deviation)
        assert class_counts[CAR] <= 120 * (1 + deviation)
        # assert class_counts[TRUCK] <= 60 * (1 + deviation)
        assert class_counts[PERSON] <= 120 * (1 + deviation)
        assert class_counts[BICYCLE] <= 60 * (1 + deviation)


class TestTimestamper:
    @pytest.mark.parametrize(
        "file_name, start_date",
        [
            (
                "prefix_FR20_2022-01-01_00-00-00.mp4",
                datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            ),
            (
                "Test-Cars_FR20_2022-02-03_04-05-06.mp4",
                datetime(2022, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
            ),
            (
                "Test_Cars_FR20_2022-02-03_04-05-06.mp4",
                datetime(2022, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
            ),
            (
                "Test_Cars_2022-02-03_04-05-06.mp4",
                datetime(2022, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
            ),
            (
                "2022-02-03_04-05-06.mp4",
                datetime(2022, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
            ),
            (
                "2022-02-03_04-05-06-suffix.mp4",
                datetime(2022, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
            ),
        ],
    )
    def test_get_start_time_from(self, file_name: str, start_date: datetime) -> None:
        parsed_date = Timestamper()._get_start_time_from(Path(file_name))

        assert parsed_date == start_date

    def test_stamp_frames(self) -> None:
        start_date = datetime(2022, 1, 2, 3, 4, 5)
        time_per_frame = timedelta(microseconds=10000)
        detections: dict[str, dict[str, dict]] = {
            METADATA: {},
            DATA: {
                "1": {DETECTIONS: []},
                "2": {DETECTIONS: [{CLASS: "car"}]},
                "3": {DETECTIONS: []},
            },
        }

        second_frame = start_date + time_per_frame
        third_frame = second_frame + time_per_frame
        expected_dict = copy.deepcopy(detections)
        expected_dict[DATA]["1"][OCCURRENCE] = start_date.timestamp()
        expected_dict[DATA]["2"][OCCURRENCE] = second_frame.timestamp()
        expected_dict[DATA]["3"][OCCURRENCE] = third_frame.timestamp()
        stamped_dict = Timestamper()._stamp(detections, start_date, time_per_frame)

        assert expected_dict == stamped_dict


@pytest.fixture
def paths_with_illegal_fileformats() -> list[Path]:
    return [Path("err_a.video"), Path("err_b.image")]
