import io
import subprocess
import zipfile
from types import SimpleNamespace

import pytest

from app.artifacts.files import (
    PPTX_MIME,
    SandboxFileMissingError,
    detect_mime,
    read_bytes,
)
from app.exceptions import DomainValidationError


class LocalExecution:
    """Run the exact extraction script against disposable fixture files."""

    def execute(self, command, *, timeout):
        result = subprocess.run(
            command, shell=True, capture_output=True, timeout=timeout, text=True
        )
        return SimpleNamespace(
            exit_code=result.returncode, output=result.stdout, truncated=False
        )


def test_binary_read_and_limits(tmp_path):
    path = tmp_path / "a 'quoted' file.pptx"
    path.write_bytes(bytes(range(256)))
    assert read_bytes(LocalExecution(), str(path), [str(tmp_path)], 256) == bytes(
        range(256)
    )
    with pytest.raises(DomainValidationError):
        read_bytes(LocalExecution(), str(path), [str(tmp_path)], 255)


def test_traversal_symlinks_and_outside_paths(tmp_path):
    source = tmp_path / "secret"
    source.write_text("secret")
    link = tmp_path / "link"
    link.symlink_to(source)
    for path, roots in [
        (str(link), [str(tmp_path)]),
        (str(source), ["/workspace"]),
        (str(tmp_path / "../secret"), [str(tmp_path)]),
    ]:
        with pytest.raises(DomainValidationError):
            read_bytes(LocalExecution(), path, roots, 100)


def test_missing_is_distinct_from_invalid(tmp_path):
    with pytest.raises(SandboxFileMissingError):
        read_bytes(LocalExecution(), str(tmp_path / "gone"), [str(tmp_path)], 100)


def test_pptx_validation_and_utf8():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ppt/presentation.xml", "<presentation/>")
    assert detect_mime("report.pptx", buffer.getvalue()) == PPTX_MIME
    with pytest.raises(DomainValidationError):
        detect_mime("report.pptx", b"not a zip")
    with pytest.raises(DomainValidationError):
        detect_mime("data.csv", b"\xff")
    assert detect_mime("report.pdf", b"not pdf") == "application/octet-stream"


def test_pptx_zip_bomb_is_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ppt/presentation.xml", b"0" * (101 * 1024 * 1024))
    with pytest.raises(DomainValidationError, match="expands"):
        detect_mime("report.pptx", buffer.getvalue())


def test_transport_failure_is_typed():
    from app.artifacts.files import SandboxReadError

    def unreachable(*_args, **_kwargs):
        raise RuntimeError("gateway unreachable")

    backend = SimpleNamespace(execute=unreachable)
    with pytest.raises(SandboxReadError):
        read_bytes(backend, "/tmp/report.csv", ["/tmp"], 100)
