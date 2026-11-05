import io

from apps.cli.progress import Progress, track


class FakeTty(io.StringIO):
    def isatty(self):
        return True


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_without_terminal_logs_periodic_lines_not_a_bar():
    stream, clock = io.StringIO(), Clock()
    with Progress("Quét web", total=100, stream=stream, every_s=30, clock=clock) as bar:
        bar.update()  # chưa tới hạn: không in
        clock.now = 31
        bar.update(note="lỗi 2")
    lines = stream.getvalue().splitlines()
    assert lines[0].startswith("Quét web: 2/100") and "lỗi 2" in lines[0]
    assert lines[-1].startswith("Quét web: xong 2/100")
    assert "\r" not in stream.getvalue()


def test_total_can_grow_while_running():
    stream, clock = io.StringIO(), Clock()
    with Progress("Quét web", stream=stream, every_s=1, clock=clock) as bar:
        clock.now = 2
        bar.update(total=10)
        clock.now = 4
        bar.update(total=50)
    assert "2/50" in stream.getvalue()


def test_terminal_draws_a_bar():
    stream = FakeTty()
    with Progress("Lọc", total=4, stream=stream) as bar:
        bar.update(4)
    assert "Lọc" in stream.getvalue() and "4/4" in stream.getvalue()


def test_track_yields_every_item_and_reports_them():
    stream = io.StringIO()
    assert list(track(["a", "b"], "Ảnh", stream=stream)) == ["a", "b"]
    assert "xong 2/2" in stream.getvalue()
