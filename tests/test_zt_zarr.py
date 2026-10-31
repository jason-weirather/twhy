"""Required real Zarr/HTTP integration for the T/Z frontend, not codec doubles."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading

import numpy as np
import pytest
from click.testing import CliRunner

from twhy import ViewSession, Viewport
from twhy.cli import main
from twhy.image_document import ImageDocument
from test_zt_navigation import browsing_stack
from test_viewer import send
from zt_zarr_fixture import write_zarr_stack


@pytest.mark.parametrize("version", ["0.4", "0.5", "0.6"])
@pytest.mark.parametrize("axes", ["tczyx", "tcxyz", "czyx", "tcyx"])
def test_real_zarr_planes_defaults_and_permuted_storage(tmp_path, version, axes):
    path = tmp_path / "input.zarr"
    values, _ = write_zarr_stack(path, version=version, axes=axes)
    doc = ImageDocument(path)
    initial = doc.initialize()
    later = None
    try:
        assert initial.z_index == (0 if "z" in axes else None)
        assert initial.t_index == (0 if "t" in axes else None)
        z, t = (4 if "z" in axes else None), (2 if "t" in axes else None)
        later = doc.load_plane(0, z_index=z, t_index=t)
        kept = "".join(a for a in axes if a not in "tz")
        selection = tuple(z if a == "z" else t if a == "t" else slice(None) for a in axes)
        expected = values[selection].transpose(tuple(kept.index(a) for a in "cyx"))
        np.testing.assert_array_equal(later.image.read_region(0, 32, 0, 48), expected)
        assert later.dataset is initial.dataset
    finally:
        if later is not None:
            later.release()
        initial.release()
        doc.close()


@pytest.mark.parametrize("sharded", [False, True])
def test_zarr_cache_reused_across_t_z_and_channel_changes(tmp_path, sharded):
    path = tmp_path / "cached.zarr"
    values, _ = write_zarr_stack(path, sharded=sharded)
    doc = ImageDocument(path)
    first = doc.initialize()
    dataset = first.dataset
    try:
        for t, z, c in [(0, 0, 0), (2, 1, 1), (0, 0, 0)]:
            item = doc.load_plane(0, z_index=z, t_index=t)
            try:
                with ViewSession(item.image, cache_mib=0, overview_cache_mib=0) as session:
                    samples = session.sample(session.plan(Viewport(0, 0, 8, 8), rows=8,
                                                          columns=8, channels=(c,)))
                    np.testing.assert_array_equal(samples.values[0], values[t, c, z, :8, :8])
                assert dataset.cache_info()["loads"] == 1
            finally:
                item.release()
    finally:
        first.release()
        doc.close()


@pytest.mark.parametrize("version", ["0.4", "0.5", "0.6"])
def test_xyz_pyramid_never_substitutes_a_different_z_observation(tmp_path, version):
    path = tmp_path / "xyz.zarr"
    values, _ = write_zarr_stack(path, version=version, pyramid="xyz")
    doc = ImageDocument(path, z_index=3, t_index=2)
    item = doc.initialize()
    try:
        assert [level.plane_preserving for level in item.dataset.levels] == [True, True, False]
        assert len(item.image.levels) == 2
        np.testing.assert_array_equal(item.image.read_region(0, 32, 0, 48), values[2, :, 3])
        with ViewSession(item.image, max_read_pixels=10000) as session:
            plan = session.plan(Viewport(0, 0, 48, 32), rows=4, columns=4)
            assert plan.level.index == 1
            assert plan.level.scale_x == 2  # native XYZ level 2 would have scale 4
            assert session.sample(plan).values.shape == (1, 4, 4)
    finally:
        item.release()
        doc.close()


def test_http_plane_steps_reuse_chunks_without_metadata_rediscovery(tmp_path):
    write_zarr_stack(tmp_path / "http.zarr")
    requests = []
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            super().do_GET()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    doc = ImageDocument(f"http://127.0.0.1:{server.server_port}/http.zarr")
    first = second = None
    try:
        first = doc.initialize()
        first.image.read_region(0, 8, 0, 8, channels=(0,))
        requests.clear()
        second = doc.load_plane(0, z_index=1, t_index=2)
        second.image.read_region(0, 8, 0, 8, channels=(1,))
        assert not requests
    finally:
        if second is not None:
            second.release()
        if first is not None:
            first.release()
        doc.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def test_real_zarr_keyboard_and_snapshot(tmp_path):
    path = tmp_path / "viewer.zarr"
    write_zarr_stack(path)
    async with browsing_stack(path) as (nav, viewer, pipe, _, task):
        await send(pipe, "]d]", viewer, task)
        assert nav.active.position == (0, 1, 1)
    out = tmp_path / "snapshot.txt"
    result = CliRunner().invoke(main, [str(path), "--z-index", "2", "--t-index", "1",
                                      "--snapshot", "--rows", "8", "--columns", "20",
                                      "-o", str(out)])
    assert result.exit_code == 0, (result.output, result.exception)
    assert len(out.read_text().splitlines()) == 8


def test_zarr_absent_axis_is_not_a_hidden_singleton_control(tmp_path):
    path = tmp_path / "time.zarr"
    write_zarr_stack(path, axes="tcyx")
    doc = ImageDocument(path, z_index=0)
    with pytest.raises(ValueError, match="no z axis"):
        doc.initialize()
    assert doc._dataset_handle is None


def test_public_demo_outputs_open_in_twhy(tmp_path):
    import importlib.util
    from pathlib import Path
    script = Path(__file__).resolve().parents[1] / "examples" / "make_zt_demo.py"
    spec = importlib.util.spec_from_file_location("zt_demo", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    outputs = module.write_demo(tmp_path / "demo")
    for path in outputs.values():
        doc = ImageDocument(path, z_index=4, t_index=2)
        item = doc.initialize()
        try:
            assert item.position == (0, 4, 2)
            assert item.image.channel_names == ("Disc", "Ring and marker")
        finally:
            item.release()
            doc.close()
    with pytest.raises(FileExistsError):
        module.write_demo(tmp_path / "demo")
