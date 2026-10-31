"""Quick whole-slide opening and snapshot policy over the shared display pipeline."""

import asyncio
import time

import numpy as np
import pytest
from click.testing import CliRunner
from omeify import MultichannelImage, RGBImage
from prompt_toolkit.input import create_pipe_input

from twhy import TextRenderer, Viewport, ViewSession
from twhy.cli import main
from twhy.startup_overview import prepare_fast_overview, startup_fit
from twhy.runtime_overview import DEFAULT_OVERVIEW_MAX_SOURCE_PIXELS
from twhy.viewer import Viewer
from test_sampled_overview import GradientSlide, SizedOutput


async def displayed(viewer, task, *, timeout=8):
    end = time.monotonic() + timeout
    while viewer.frame is None or viewer.busy or viewer.displayed_generation != viewer.generation:
        if task.done():
            await task
            raise AssertionError("Viewer exited without displaying the frame")
        if time.monotonic() > end:
            pytest.fail("Viewer did not produce a complete initial frame")
        await asyncio.sleep(.02)


def test_startup_fit_uses_native_coarse_level_without_building():
    pixels = np.arange(120 * 32, dtype=np.uint16).reshape(120, 32)
    with MultichannelImage.from_array(pixels, axes="YX") as image, ViewSession(
        image, max_read_pixels=10000,
    ) as session:
        renderer = TextRenderer(mode="simple", color=False)
        full, native = startup_fit(session, renderer, rows=10, columns=30, channels=(0,))
        assert native
        assert full.x < 0  # Tall slide letterboxes on the horizontal axis.
        assert session.overview_cache_bytes == 0
        assert not session.quick_overview_eligible()


@pytest.mark.asyncio
async def test_viewer_opens_whole_image_when_native_level_is_affordable():
    pixels = np.full((120, 32), 100, dtype=np.uint16)
    with MultichannelImage.from_array(pixels, axes="YX") as image, ViewSession(
        image, max_read_pixels=10000,
    ) as session, create_pipe_input() as pipe:
        viewer = Viewer(session, renderer=TextRenderer(mode="simple", color=False))
        task = asyncio.create_task(viewer.run(input=pipe, output=SizedOutput()))
        try:
            await displayed(viewer, task)
            assert viewer.viewport.x < 0
            assert viewer.viewport.y <= 0
            assert viewer.viewport.y + viewer.viewport.height >= 120
            assert viewer.samples.plan.sampled_overview is None
            assert session.overview_cache_bytes == 0
        finally:
            pipe.send_bytes(b"\x11")
            await asyncio.wait_for(task, 8)


@pytest.mark.asyncio
async def test_quick_reduction_finishes_before_initial_frame():
    pixels = np.full((37, 23), 170, dtype=np.uint16)
    with MultichannelImage.from_array(pixels, axes="YX") as image, ViewSession(
        image, max_read_pixels=64,
    ) as session, create_pipe_input() as pipe:
        viewer = Viewer(session, renderer=TextRenderer(mode="simple", color=False),
                        startup_overview_seconds=2.0)
        task = asyncio.create_task(viewer.run(input=pipe, output=SizedOutput()))
        try:
            await displayed(viewer, task)
            assert viewer.viewport.x <= 0 and viewer.viewport.y <= 0
            assert viewer.viewport.x + viewer.viewport.width >= 23
            assert viewer.viewport.y + viewer.viewport.height >= 37
            assert viewer.samples.cached_overview
            assert viewer.displayed_generation == viewer.generation
            assert "cached overview" in viewer._status()
        finally:
            pipe.send_bytes(b"\x11")
            await asyncio.wait_for(task, 8)




@pytest.mark.asyncio
async def test_large_fast_slide_first_image_is_cached_not_sampled(monkeypatch):
    """An SVS-scale coarsest level can exceed the old hidden 8M-sample gate.

    The first *rendered* frame, not merely the last frame observed after idle
    refinement, must use the full-coverage overview when the time budget allows.
    """
    from importlib import import_module

    source = GradientSlide(64_000, 14_000)
    assert source.shapes[-1][0] * source.shapes[-1][1] * 3 > 8_388_608
    with RGBImage(source) as image, ViewSession(image) as session, \
            create_pipe_input() as pipe:
        assert session.quick_overview_eligible()  # Regression: previously False.
        module = import_module("twhy.viewer.viewer")
        original = module.make_frame
        first_frames = []

        def record_first_frame(session, request):
            result = original(session, request)
            first_frames.append(result.samples.cached_overview)
            return result

        monkeypatch.setattr(module, "make_frame", record_first_frame)
        viewer = Viewer(session, renderer=TextRenderer(mode="blocks"),
                        startup_overview_seconds=5)
        task = asyncio.create_task(viewer.run(input=pipe, output=SizedOutput()))
        try:
            await displayed(viewer, task, timeout=12)
            assert first_frames == [True]  # No sparse image was ever painted.
            assert viewer.samples.cached_overview
            assert viewer.viewport == Viewport.fit(session.info.shape, columns=68, rows=26)
            assert "cached overview" in viewer._status()
        finally:
            pipe.send_bytes(b"\x11")
            await asyncio.wait_for(task, 8)


def test_snapshot_startup_policy_accepts_larger_fast_coarse_level():
    """Shared synchronous preparation should also honor time, not a fixed 8M cap."""
    source = GradientSlide(64_000, 14_000)
    with RGBImage(source) as image, ViewSession(image) as session:
        assert session.quick_overview_eligible()
        assert prepare_fast_overview(session, (0,), seconds=5)
        full, native = startup_fit(session, TextRenderer(mode="blocks"),
                                   columns=68, rows=26, channels=(0,))
        assert not native
        plan = session.plan(full, rows=52, columns=68, allow_sampled_overview=True)
        assert plan.sampled_overview is not None
        assert session.sample(plan).cached_overview


@pytest.mark.asyncio
async def test_small_deadline_still_opens_whole_slide_with_sampled_preview(monkeypatch):
    source = GradientSlide(3200, 1600)
    with RGBImage(source) as image, ViewSession(
        image, max_read_pixels=500,
    ) as session, create_pipe_input() as pipe:
        original = session.step_overview
        calls = []

        def slow_step(channels):
            calls.append(1)
            time.sleep(.025)
            return original(channels)

        monkeypatch.setattr(session, "step_overview", slow_step)
        viewer = Viewer(session, renderer=TextRenderer(mode="blocks"),
                        startup_overview_seconds=.001)
        task = asyncio.create_task(viewer.run(input=pipe, output=SizedOutput()))
        try:
            await displayed(viewer, task)
            assert calls
            assert viewer.viewport == Viewport.fit(session.info.shape, columns=68, rows=26)
            assert viewer.samples.plan.sampled_overview is not None
            assert not viewer.samples.cached_overview
            # The unfinished build is permitted to resume during later idle time.
            assert viewer.displayed_generation == viewer.generation
        finally:
            pipe.send_bytes(b"\x11")
            await asyncio.wait_for(task, 8)


@pytest.mark.asyncio
async def test_very_large_scan_is_not_attempted_during_open(monkeypatch):
    source = GradientSlide(128_000, 100_000)
    with RGBImage(source) as image, ViewSession(image, max_read_pixels=1000) as session, \
            create_pipe_input() as pipe:
        # The coarsest stored level exceeds the explicitly configurable total-scan cap.
        assert not session.quick_overview_eligible()
        original = session.step_overview
        observed = []

        def monitored(channels):
            observed.append(viewer.frame is not None)
            return original(channels)

        monkeypatch.setattr(session, "step_overview", monitored)
        viewer = Viewer(session, renderer=TextRenderer(mode="blocks"))
        task = asyncio.create_task(viewer.run(input=pipe, output=SizedOutput()))
        try:
            await displayed(viewer, task)
            assert viewer.viewport == Viewport.fit(session.info.shape, columns=68, rows=26)
            assert viewer.samples.plan.sampled_overview is not None
            assert not viewer.samples.cached_overview
            assert all(observed)  # Idle scheduler runs only after the first frame.
            # Normal idle preparation may already have started after first paint;
            # it is not part of the quick pre-first-frame decision.
        finally:
            pipe.send_bytes(b"\x11")
            await asyncio.wait_for(task, 8)


@pytest.mark.asyncio
async def test_default_read_budget_never_forces_a_center_crop():
    """A large slide with a real pyramid can still exceed 4M RGB samples."""
    source = GradientSlide(60_000, 10_000)
    with RGBImage(source) as image, ViewSession(
        image, overview_cache_mib=0,  # Force the bounded sampled preview, not a new scan.
    ) as session, create_pipe_input() as pipe:
        assert session.max_read_pixels == 4_194_304
        # Coarsest level alone is ~7 million RGB samples.
        assert source.shapes[-1][0] * source.shapes[-1][1] * 3 > session.max_read_pixels
        viewer = Viewer(session, renderer=TextRenderer(mode="blocks"))
        task = asyncio.create_task(viewer.run(input=pipe, output=SizedOutput()))
        try:
            await displayed(viewer, task)
            full = Viewport.fit(session.info.shape, columns=68, rows=26)
            assert viewer.viewport == full
            assert viewer.samples.plan.viewport == full
            assert viewer.samples.plan.sampled_overview is not None
            assert "sampled overview" in viewer._status()
            assert "center crop" not in viewer.message
            assert source.reads  # The bounded overview was actually sampled.
            assert sum((y1-y0)*(x1-x0)*3 for _,y0,y1,x0,x1,_ in source.reads) \
                <= session.max_read_pixels
        finally:
            pipe.send_bytes(b"\x11")
            await asyncio.wait_for(task, 8)


@pytest.mark.asyncio
async def test_explicit_initial_region_is_preserved_when_whole_fit_is_default():
    source = GradientSlide(3200, 1600)
    region = Viewport(100, 200, 200, 150)
    with RGBImage(source) as image, ViewSession(
        image, max_read_pixels=50_000,
    ) as session, create_pipe_input() as pipe:
        viewer = Viewer(session, viewport=region, renderer=TextRenderer(mode="blocks"))
        task = asyncio.create_task(viewer.run(input=pipe, output=SizedOutput()))
        try:
            await displayed(viewer, task)
            assert viewer.viewport == region
            assert viewer.samples.plan.viewport == region
            assert viewer.samples.plan.sampled_overview is None
        finally:
            pipe.send_bytes(b"\x11")
            await asyncio.wait_for(task, 8)


def test_snapshot_full_slide_from_quick_cache_and_sparse_fallback(mif, tmp_path):
    path = str(mif[0])
    base = [path, "--snapshot", "--columns", "31", "--rows", "13",
            "--max-read-pixels", "100"]
    cases = [([], "Cached full-coverage overview"),
             (["--startup-overview-seconds", "0"], "Sampled overview"),
             (["--overview-cache-mib", "0"], "Sampled overview")]
    for index, (options, diagnostic) in enumerate(cases):
        output = tmp_path / f"snapshot-{index}.txt"
        result = CliRunner().invoke(main, [*base, *options, "-o", str(output)])
        assert result.exit_code == 0, result.output
        assert diagnostic in result.output
        # Snapshot contents are independent of Click's version-specific stderr
        # mixing in its test runner. Diagnostics are not extra rendered rows.
        text = output.read_text()
        assert len(text.splitlines()) == 13
        assert all(len(line) == 31 for line in text.splitlines())
        assert text.endswith("\n")


def test_snapshot_deadline_is_checked_between_chunks(monkeypatch, mif):
    import twhy.startup_overview as startup

    clock = iter([0, .3, .6, .9, 1.2])
    monkeypatch.setattr(startup, "monotonic", lambda: next(clock, 1.3))
    result = CliRunner().invoke(main, [str(mif[0]), "--snapshot", "--max-read-pixels", "10",
                                       "--startup-overview-seconds", "1"])
    assert result.exit_code == 0, result.output
    assert "Sampled overview" in result.output


def test_scan_preflight_respects_memory_and_work_limits():
    slide = GradientSlide(128_000, 100_000)
    with RGBImage(slide) as image, ViewSession(image, max_read_pixels=1000) as session:
        assert not session.quick_overview_eligible()
        assert DEFAULT_OVERVIEW_MAX_SOURCE_PIXELS < 8000 * 6250 * 3
        assert not prepare_fast_overview(session, (0,), seconds=2)
        assert slide.reads == []
    with MultichannelImage.from_array(np.ones((10, 10)), axes="YX") as image, ViewSession(
        image, max_read_pixels=10, overview_cache_mib=0,
    ) as session:
        assert not session.quick_overview_eligible()
        assert not prepare_fast_overview(session, (0,), seconds=2)

@pytest.mark.parametrize("kind", ["svs", "ome"])
def test_real_tiff_reader_uses_quick_full_coverage_reduction(tmp_path, kind):
    """Both vendor TIFF readers share the same actual regional decoding path."""
    from twhy import open_image
    from test_svs import synthetic_svs
    from conftest import write_pyramid

    path = tmp_path / ("slide.svs" if kind == "svs" else "slide.ome.tif")
    if kind == "svs":
        synthetic_svs(path)
    else:
        pixels = np.arange(160 * 128 * 3, dtype=np.uint8).reshape(128, 160, 3)
        write_pyramid(path, pixels, rgb=True)
    with open_image(path) as image, ViewSession(
        image, max_read_pixels=96, overview_cache_mib=2,
    ) as session:
        full, native = startup_fit(session, TextRenderer(mode="blocks"),
                                   columns=30, rows=10, channels=(0,))
        assert not native
        assert session.quick_overview_eligible()
        assert prepare_fast_overview(session, (0,), seconds=5)
        plan = session.plan(full, rows=20, columns=30, allow_sampled_overview=True)
        assert plan.sampled_overview is not None
        samples = session.sample(plan)
        assert samples.cached_overview
        assert np.isfinite(samples.values).any()
        assert len(image.levels) >= 3
        assert session.overview_cache_bytes <= 2 * 1024**2


def test_real_svs_cli_snapshot_shows_all_pixels_without_crop(tmp_path):
    from test_svs import synthetic_svs

    path = tmp_path / "slide.svs"
    synthetic_svs(path)
    args = [str(path), "--snapshot", "--ansi", "--mode", "blocks",
            "--max-read-pixels", "96", "--startup-overview-seconds", "5",
            "--columns", "30", "--rows", "10"]
    rendered = CliRunner().invoke(main, args)
    assert rendered.exit_code == 0, rendered.output
    assert "Cached full-coverage overview" in rendered.output
    assert "\x1b[" in rendered.output
    assert "bounded center crop" not in rendered.output

def test_real_svs_terminal_opens_full_sampled_view_without_a_fit_key(tmp_path):
    """Exercise actual CLI terminal startup, not only the internal fit helper."""
    import os
    import sys

    if sys.platform == "win32":
        pytest.skip("POSIX pseudo-terminal test")
    pexpect = pytest.importorskip("pexpect")
    from test_svs import synthetic_svs

    path = tmp_path / "pyramid.svs"
    synthetic_svs(path)
    env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"}
    env.pop("NO_COLOR", None)
    env.pop("PROMPT_TOOLKIT_COLOR_DEPTH", None)
    child = pexpect.spawn(
        sys.executable,
        ["-m", "twhy", str(path), "--max-read-pixels", "96",
         "--overview-cache-mib", "0", "--startup-overview-seconds", "0"],
        dimensions=(30, 120), encoding="utf-8", env=env, timeout=15,
    )
    try:
        # Without the fix, the initial bounded crop has no sampled-overview
        # marker until the user explicitly presses r or zooms out.
        child.expect("sampled overview")
        child.send("q")
        child.expect(pexpect.EOF)
    finally:
        child.close(force=True)
    assert child.exitstatus == 0


@pytest.mark.asyncio
async def test_user_zoom_preempts_quick_start_without_late_recenter(monkeypatch):
    from threading import Event

    source = GradientSlide(3200, 1600)
    entered, release = Event(), Event()
    with RGBImage(source) as image, ViewSession(image, max_read_pixels=500) as session, \
            create_pipe_input() as pipe:
        original = session.step_overview

        def gated(channels):
            entered.set()
            assert release.wait(8), "Release the current TIFF chunk"
            return original(channels)

        monkeypatch.setattr(session, "step_overview", gated)
        viewer = Viewer(session, renderer=TextRenderer(mode="blocks"),
                        startup_overview_seconds=2)
        task = asyncio.create_task(viewer.run(input=pipe, output=SizedOutput()))
        try:
            until = time.monotonic() + 5
            while not entered.is_set():
                if task.done():
                    await task
                assert time.monotonic() < until
                await asyncio.sleep(.01)
            before = viewer.generation
            pipe.send_text("+")
            while viewer.generation == before:
                assert time.monotonic() < until
                await asyncio.sleep(.01)
            chosen = viewer.viewport
            release.set()
            await displayed(viewer, task)
            assert viewer.viewport == chosen
            assert viewer.samples.plan.viewport == chosen
            assert viewer.viewport.height < 3200
        finally:
            release.set()
            pipe.send_bytes(b"\x11")
            await asyncio.wait_for(task, 8)
