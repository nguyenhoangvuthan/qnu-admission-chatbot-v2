import json

import pytest

from qnuchat.ingest.ocr import worker


def boxes(*sizes):
    return [{"box": [0, 0, w, h]} for w, h in sizes]


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(b"anh")
    return {"id": "a", "path": str(path), "sha256": worker.sha256_file(path)}


def run(items, out, ocr, **kwargs):
    return worker.run(
        items,
        out,
        load=lambda: ocr,
        check=lambda: None,
        env=lambda: {"config": worker.CONFIG},
        **kwargs,
    )


def test_page_is_sideways_only_when_most_long_boxes_stand_upright():
    assert worker.is_sideways(boxes(*[(20, 100)] * 10))
    assert not worker.is_sideways(boxes(*[(100, 20)] * 10))
    assert not worker.is_sideways(boxes(*[(20, 100)] * 9))  # quá ít khung để kết luận
    assert not worker.is_sideways(boxes(*[(20, 100)] * 7, *[(100, 20)] * 3))
    assert not worker.is_sideways(boxes(*[(50, 50)] * 20))  # khung vuông không tính


def test_sideways_angle_picks_the_better_of_90_and_270():
    res = {"label_names": ["0", "90", "180", "270"], "scores": [0.9, 0.02, 0.01, 0.07]}
    assert worker.sideways_angle(res) == 270


def test_sideways_angle_refuses_missing_scores():
    with pytest.raises(ValueError):
        worker.sideways_angle({"label_names": ["0", "180"], "scores": [0.5, 0.5]})


def test_vietocr_config_is_read_locally_without_pretrained_download(tmp_path):
    base, named = tmp_path / "base.yml", tmp_path / "named.yml"
    base.write_text("a: 1\ncnn:\n  pretrained: true\n  ss: 2\n", encoding="utf-8")
    named.write_text("b: 2\n", encoding="utf-8")
    cfg = worker.load_vietocr_config(base, named)
    assert cfg["a"] == 1 and cfg["b"] == 2
    assert cfg["cnn"] == {"pretrained": False, "ss": 2}


def test_weights_with_another_hash_are_refused(tmp_path):
    with pytest.raises(worker.EnvMismatch):
        worker.check_weights(tmp_path / "models", tmp_path / "vietocr")


def test_run_writes_one_checkpoint_per_image_with_provenance(image, tmp_path):
    out = tmp_path / "out"
    lines = [{"text": "x", "box": [0, 0, 1, 1]}]
    code = run([image], out, lambda path: {"lines": lines, "rotation": 0})
    rec = json.loads((out / "a.json").read_text(encoding="utf-8"))
    assert code == worker.EXIT_OK
    assert rec["lines"][0]["text"] == "x" and rec["rotation"] == 0
    assert rec["config"] == "cur_rotgate" and rec["image_sha256"] == image["sha256"]
    assert rec["env_sha256"] == worker.env_sha256({"config": worker.CONFIG})


def test_rerun_skips_finished_images(image, tmp_path):
    calls = []

    def ocr(path):
        calls.append(path)
        return {"lines": [], "rotation": 0}

    run([image], tmp_path / "out", ocr)
    run([image], tmp_path / "out", ocr)
    assert len(calls) == 1


def test_engine_failure_is_an_execution_error_not_an_empty_page(image, tmp_path):
    def ocr(path):
        raise RuntimeError("hỏng")

    out = tmp_path / "out"
    assert run([image], out, ocr) == worker.EXIT_OK
    rec = json.loads((out / "a.json").read_text(encoding="utf-8"))
    assert "lines" not in rec and rec["error"]["kind"] == "exception"


def test_retry_errors_runs_failed_images_again(image, tmp_path):
    def broken(path):
        raise RuntimeError("hỏng")

    out = tmp_path / "out"
    run([image], out, broken)
    run([image], out, lambda path: {"lines": [], "rotation": 0})  # không có cờ: giữ bản ghi lỗi
    assert "error" in json.loads((out / "a.json").read_text(encoding="utf-8"))
    run([image], out, lambda path: {"lines": [], "rotation": 0}, retry_errors=True)
    assert json.loads((out / "a.json").read_text(encoding="utf-8"))["lines"] == []


def test_image_with_another_hash_is_an_execution_error(image, tmp_path):
    out = tmp_path / "out"
    run([{**image, "sha256": "khac"}], out, lambda path: {"lines": [], "rotation": 0})
    rec = json.loads((out / "a.json").read_text(encoding="utf-8"))
    assert rec["error"]["kind"] == "image_hash_mismatch"


def test_checkpoints_of_another_environment_are_not_mixed(image, tmp_path):
    out = tmp_path / "out"
    run([image], out, lambda path: {"lines": [], "rotation": 0})
    code = worker.run(
        [image],
        out,
        load=lambda: None,
        check=lambda: None,
        env=lambda: {"config": "khac"},
    )
    assert code == worker.EXIT_ENV_MISMATCH


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (worker.GpuUnavailable("x"), worker.EXIT_GPU_UNAVAILABLE),
        (worker.LoadFailed("x"), worker.EXIT_LOAD_FAILED),
        (OSError("x"), worker.EXIT_LOAD_FAILED),
    ],
)
def test_load_failures_stop_with_their_own_exit_code(tmp_path, exc, code):
    def load():
        raise exc

    assert worker.run([], tmp_path / "out", load=load) == code
