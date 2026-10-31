"""Real local HTTP staging, S3 dispatch contracts, and native Zarr reader routing."""
from __future__ import annotations

import asyncio
import io
import sys
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image as PILImage

from twhy import open_image
from twhy.cli import main
from twhy.image_document import ImageDocument
from twhy.image_input import image_kind
from twhy.source_input import display_name, is_zarr_input, resolve_input, s3_options
from twhy.view_info import ViewInfo
from twhy.viewer.file_viewer import view_file


@contextmanager
def serve(directory: Path):
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(directory)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_remote_detection_and_s3_endpoint(tmp_path):
    store = tmp_path / "mydata"
    store.mkdir()
    (store / "zarr.json").write_text("{}")
    assert is_zarr_input(store) and image_kind(store) == "zarr"
    assert is_zarr_input("s3://bucket/dataset.ome.zarr")
    assert is_zarr_input("https://example.org/stores/", input_format="zarr")
    assert display_name("https://example.org/data/fig.png?token=SENSITIVE") == "fig.png"
    assert s3_options("http://localhost:9000") == {
        "client_kwargs": {"endpoint_url": "http://localhost:9000"}}
    assert s3_options(anonymous=True) == {"anon": True}
    assert s3_options("http://localhost:9000", anonymous=True) == {
        "client_kwargs": {"endpoint_url": "http://localhost:9000"}, "anon": True}
    with pytest.raises(ValueError):
        s3_options("http://username:secret@localhost:9000")
    with pytest.raises(ValueError):
        with resolve_input("ftp://example.org/a.png"):
            pass
    with pytest.raises(ValueError):
        with resolve_input("s3://bucket/../escape.ome.zarr"):
            pass
    with pytest.raises(ValueError):
        with resolve_input("https://example.org/a.ome.zarr?secret=xyz"):
            pass


def test_http_raster_snapshot_and_download_cap(tmp_path):
    data = np.zeros((64, 72, 3), dtype=np.uint8)
    data[:, :, 0] = np.arange(72, dtype=np.uint8)
    file = tmp_path / "sample.png"
    PILImage.fromarray(data).save(file)
    original = file.read_bytes()
    with serve(tmp_path) as url:
        address = f"{url}/sample.png?token=private-value"
        with resolve_input(address) as resource:
            assert resource.remote and resource.path.is_file()
            assert resource.label == "sample.png"
            assert resource.path.read_bytes() == original
            temp = resource.path
        assert not temp.exists()
        result = CliRunner().invoke(main, [address, "--snapshot", "--columns", "20", "--rows", "8"])
        assert result.exit_code == 0, (result.output, result.exception)
        assert len(result.stdout.splitlines()) == 8
        assert "private-value" not in result.output
        with open_image(address) as image:
            np.testing.assert_array_equal(image.read_region(0, 64, 0, 72), data)
        result = CliRunner().invoke(main, [address, "--snapshot", "--max-remote-mib", "0.000001"])
        assert result.exit_code != 0
        assert "exceeds --max-remote-mib" in result.output
        assert "private-value" not in result.output
    assert file.read_bytes() == original


def test_http_pdf_page_snapshot_and_lifetime(tmp_path, monkeypatch):
    pytest.importorskip("pypdfium2")
    from test_image_input import write_pdf
    write_pdf(tmp_path / "document.pdf")
    with serve(tmp_path) as url:
        address = url + "/document.pdf"
        result = CliRunner().invoke(main, [address, "--snapshot", "--pdf-max-dpi", "72",
                                           "--columns", "20", "--rows", "7"])
        assert result.exit_code == 0, (result.output, result.exception)
        assert len(result.stdout.splitlines()) == 7
        from twhy.viewer import file_viewer
        observed = []

        async def check_live(path, **kwargs):
            assert isinstance(path, Path) and path.is_file()
            assert path.read_bytes().startswith(b"%PDF-")
            observed.append(path)
            assert ImageDocument(path).kind == "pdf"

        monkeypatch.setattr(file_viewer, "_view_resolved_file", check_live)
        asyncio.run(view_file(address))
        assert observed and not observed[0].exists()


def test_s3_single_file_uses_optional_transport(tmp_path, monkeypatch):
    import fsspec
    payload = b"\x89PNG\r\n\x1a\n" + b"A" * 32
    calls = []

    @contextmanager
    def fake_open(url, mode="rb", **options):
        calls.append((url, mode, options))
        yield io.BytesIO(payload)

    monkeypatch.setitem(sys.modules, "s3fs", SimpleNamespace())
    monkeypatch.setattr(fsspec, "open", fake_open)
    with resolve_input("s3://localbucket/a.png", s3_endpoint_url="http://localhost:9000") as item:
        assert item.path.read_bytes() == payload
        old_path = item.path
    assert not old_path.exists()
    assert calls[0] == ("s3://localbucket/a.png", "rb", {
        "client_kwargs": {"endpoint_url": "http://localhost:9000"}})


def test_zarr_reader_routes_group_series_and_s3_options(monkeypatch):
    import omeify
    recorded = []

    class FakeZarr:
        def __init__(self, path, **options):
            recorded.append((path, options))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(omeify, "OMEZarrReader", FakeZarr)
    with open_image("s3://localbucket/a.ome.zarr", series=2, group="A/1/0", z_index=1,
                    t_index=3, s3_endpoint_url="http://localhost:9000") as image:
        assert isinstance(image, FakeZarr)
    assert recorded == [("s3://localbucket/a.ome.zarr", {
        "series": 2, "group": "A/1/0", "z": 1, "t": 3,
        "storage_options": {"client_kwargs": {"endpoint_url": "http://localhost:9000"}},
    })]
    with open_image("https://example.org/stores/no-suffix", input_format="zarr") as image:
        assert isinstance(image, FakeZarr)


def test_shifted_levels_never_selected_for_viewing():
    """An off-grid nearest pyramid must not move data or overview sample positions."""
    from omeify import ImageLevel, MultichannelImage
    from twhy import ViewSession
    from twhy.viewport import Viewport

    data = np.arange(32*32, dtype=np.uint16).reshape(32, 32)
    # Nearest-neighbor level has nonzero pixel-edge origin relative to the base.
    layers = (data, data[::2, ::2])
    levels = (ImageLevel(0, "YX", data.shape, downsample_yx=(1, 1)),
              ImageLevel(1, "YX", layers[1].shape, downsample_yx=(2, 2),
                         offset_yx=(-.5, -.5)))
    with MultichannelImage.from_array(data, axes="YX", level_arrays=layers[1:],
                                       levels=levels) as image:
        info = ViewInfo.from_image(image, name="shifted")
        assert [level.index for level in info.levels] == [0]
        with ViewSession(image, max_read_pixels=2048) as session:
            planned = session.plan(Viewport(0, 0, 32, 32), rows=8, columns=8)
            assert planned.level.index == 0
            sampled = session.sample(planned)
            assert np.isfinite(sampled.values).all()


def test_zarr_collection_navigation_for_url_root(monkeypatch):
    # Transport/dispatch unit test, not a Zarr codec substitute. Real Zarr/HTTP
    # round trips are tested independently in test_zt_zarr.py.
    import omeify
    seen, inspected, datasets = [], [], []

    def open_dataset(location, **kwargs):
        seen.append((location, kwargs))
        dataset = omeify.ImageDataset.from_array(
            np.zeros((4, 1, 3, 8, 8), np.uint16), axes="TCZYX")
        datasets.append(dataset)
        return dataset

    class Inspector:
        def __init__(self, location, **kwargs):
            inspected.append((location, kwargs))
            self.report = {"series": [{"name": name} for name in
                                      ("Stroma", "Tonsil", "Melanoma")]}

    monkeypatch.setattr(omeify, "open_dataset", open_dataset)
    monkeypatch.setattr(omeify, "ZarrInspector", Inspector)
    url = "https://example.org/collection.ome.zarr"
    document = ImageDocument(url, series=1, group="A/1", z_index=2, t_index=3)
    assert document.kind == "zarr" and document.label == "series"
    initial = document.initialize()
    try:
        assert document.count == 3 and initial.position == (1, 2, 3)
        second = document.load(2)
        assert second.position == (2, 0, 0)  # new series starts on its first plane
        second.release()
        assert "collection.ome.zarr" in document.item_name(initial)
        assert seen == [(url, {"input_type": "ome_zarr", "series": index,
                               "group": "A/1", "storage_options": None}) for index in (1, 2)]
        assert len(inspected) == 1
        assert datasets[0].is_open and not datasets[1].is_open
    finally:
        initial.release()
        document.close()
    assert not any(dataset.is_open for dataset in datasets)


def test_http_tiff_regions_and_series(mif):
    path, arrays = mif
    with serve(path.parent) as root:
        url = root + "/" + path.name
        with open_image(url, series=0) as image:
            assert len(image.levels) > 1
            patch = image.read_region(0, 20, 0, 16, channels=[1])
            np.testing.assert_array_equal(patch, arrays[0][1:2, 0:20, 0:16])
        result = CliRunner().invoke(main, [url, "--snapshot", "--rows", "8", "--columns", "20"])
        assert result.exit_code == 0, (result.output, result.exception)
