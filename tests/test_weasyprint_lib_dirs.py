"""The PDF fallback was looking for libraries where they used to live.

`nixpacks.toml` dropped `aptPkgs` because the same libraries were already
coming from `nixPkgs` — true for the app itself, but the WeasyPrint subprocess
fallback had `/usr/lib/x86_64-linux-gnu` hard-coded, with a comment saying
"apt library dirs". After the change those directories still existed (193
files, measured inside the container on 2026-11-23) and contained no
`libgobject*` at all, so the fallback symlinked 193 irrelevant libraries and
failed with exactly the error it existed to rescue:

    OSError: cannot load library 'libgobject-2.0-0'

So a directory now has to earn its place by containing a library WeasyPrint
actually asks for. That rule holds whether they arrive from apt or from
/nix/store, which is the point.
"""
from pathlib import Path

from api.services.marketing_plan_pdf import (
    _WEASYPRINT_SONAMES,
    _prepare_weasyprint_lib_dir,
    weasyprint_lib_dirs,
)


def _lib(dir_path: Path, name: str) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    target = dir_path / name
    target.write_bytes(b"\x7fELF")
    return target


def test_the_sonames_include_the_one_that_failed_in_production():
    assert "libgobject-2.0.so.0" in _WEASYPRINT_SONAMES
    assert "libpango-1.0.so.0" in _WEASYPRINT_SONAMES


def test_an_apt_dir_holding_what_we_need_is_used(tmp_path):
    apt = tmp_path / "usr-lib"
    _lib(apt, "libgobject-2.0.so.0")

    found = weasyprint_lib_dirs(apt_dirs=(str(apt),), nix_store=str(tmp_path / "empty-store"))
    assert found == [str(apt)]


def test_an_apt_dir_that_lost_its_libraries_is_skipped(tmp_path):
    """The regression itself: the directory is there, the libraries are not."""
    apt = tmp_path / "usr-lib"
    _lib(apt, "libsomethingelse.so.1")
    _lib(apt, "libz.so.1")

    found = weasyprint_lib_dirs(apt_dirs=(str(apt),), nix_store=str(tmp_path / "empty-store"))
    assert found == []


def test_the_nix_store_is_searched(tmp_path):
    store = tmp_path / "nix-store"
    glib = store / "aaaa-glib-2.82.1" / "lib"
    pango = store / "bbbb-pango-1.54.0" / "lib"
    _lib(glib, "libgobject-2.0.so.0")
    _lib(pango, "libpango-1.0.so.0")
    # A package that has nothing we need must not be pulled in.
    _lib(store / "cccc-unrelated-1.0" / "lib", "libunrelated.so.1")

    found = weasyprint_lib_dirs(apt_dirs=(), nix_store=str(store))
    assert set(found) == {str(glib), str(pango)}


def test_missing_directories_are_simply_absent(tmp_path):
    found = weasyprint_lib_dirs(
        apt_dirs=(str(tmp_path / "nope"),), nix_store=str(tmp_path / "also-nope")
    )
    assert found == []


def test_a_directory_is_never_listed_twice(tmp_path):
    """glib provides several of the sonames we look for."""
    store = tmp_path / "nix-store"
    glib = store / "aaaa-glib-2.82.1" / "lib"
    _lib(glib, "libgobject-2.0.so.0")
    _lib(glib, "libglib-2.0.so.0")
    _lib(glib, "libgio-2.0.so.0")

    found = weasyprint_lib_dirs(apt_dirs=(), nix_store=str(store))
    assert found == [str(glib)]


def test_the_subprocess_actually_gets_the_library_linked(tmp_path, monkeypatch):
    """End of the chain: the name the loader needs is in the private dir."""
    store = tmp_path / "nix-store"
    glib = store / "aaaa-glib-2.82.1" / "lib"
    _lib(glib, "libgobject-2.0.so.0")

    monkeypatch.setattr(
        "api.services.marketing_plan_pdf.weasyprint_lib_dirs",
        lambda: [str(glib)],
    )
    libdir = Path(_prepare_weasyprint_lib_dir(tmp_path / "work"))
    assert (libdir / "libgobject-2.0.so.0").exists()


def test_the_interpreters_own_toolchain_is_never_shadowed(tmp_path, monkeypatch):
    """Linking libc/libssl over the nix python's own crashes it at startup."""
    store = tmp_path / "nix-store"
    glib = store / "aaaa-glib-2.82.1" / "lib"
    _lib(glib, "libgobject-2.0.so.0")
    _lib(glib, "libc.so.6")
    _lib(glib, "libssl.so.3")

    monkeypatch.setattr(
        "api.services.marketing_plan_pdf.weasyprint_lib_dirs",
        lambda: [str(glib)],
    )
    libdir = Path(_prepare_weasyprint_lib_dir(tmp_path / "work"))
    assert (libdir / "libgobject-2.0.so.0").exists()
    assert not (libdir / "libc.so.6").exists()
    assert not (libdir / "libssl.so.3").exists()
