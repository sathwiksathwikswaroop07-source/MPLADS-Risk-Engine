"""Validating and storing photographs a citizen captures with their camera.

Every image that arrives here is re-encoded before it is written. That is the
whole point of this module rather than a `file.write(bytes)` in the route:

  * **EXIF is stripped.** A photograph off a phone carries GPS coordinates, a
    device serial and timestamps. `models.py` calls identifying data a
    liability, and it is right -- this is a government platform handling
    reports about named public figures. Re-encoding through Pillow keeps only
    the pixels, so the only location stored is the one the citizen knowingly
    consented to send.
  * **The bytes are proven to be an image.** The format is sniffed from the
    leading bytes, never taken from the filename or the client's declared
    content-type, both of which the client controls. Anything that does not
    decode is refused.
  * **The result is bounded.** Re-encoding at a capped edge length means one
    upload cannot fill the container's disk.

Nothing here writes to the database and nothing here reads a score.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from backend import config


class UploadError(ValueError):
    """The bytes are not an acceptable image. The message reaches the user."""


def sniff_format(data: bytes) -> str:
    """The image format, from the leading bytes alone.

    A filename ending in .jpg proves nothing, and neither does a
    content-type header -- both are supplied by the caller.
    """
    for magic, name in config.UPLOAD_MAGIC_BYTES.items():
        if data.startswith(magic):
            return name
    raise UploadError("Only JPEG and PNG photographs are accepted.")


def normalise(data: bytes) -> bytes:
    """Re-encode to a bounded, metadata-free JPEG.

    Returns the bytes to write. Raises UploadError if the input is too large
    or does not decode as an image.
    """
    if len(data) > config.MAX_UPLOAD_BYTES:
        limit_mb = config.MAX_UPLOAD_BYTES / (1024 * 1024)
        raise UploadError(f"The photograph must be under {limit_mb:.0f} MB.")
    if not data:
        raise UploadError("The photograph is empty.")

    sniff_format(data)

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise UploadError("That file is not a readable photograph.") from exc

    # A PNG may carry transparency and JPEG cannot; flatten rather than fail.
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    image.thumbnail((config.UPLOAD_MAX_EDGE, config.UPLOAD_MAX_EDGE))

    out = io.BytesIO()
    # A fresh image object written to a fresh buffer: no EXIF block is
    # carried across, because none is passed. Saving the original with
    # exif=b"" would be the fragile version of this.
    image.save(out, format="JPEG", quality=config.UPLOAD_JPEG_QUALITY,
               optimize=True)
    return out.getvalue()


def complaint_photo_path(work_id: int, complaint_id: int) -> str:
    """Where one complaint's photograph lives, relative to UPLOAD_DIR.

    Relative, never absolute: the column holds a key into the upload
    directory, so the store can move without rewriting every row.
    """
    return f"complaints/{work_id:06d}/{complaint_id:06d}.jpg"


def write_photo(relative_path: str, data: bytes) -> None:
    """Write normalised bytes into the upload directory."""
    target = resolve_upload(relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def resolve_upload(relative_path: str) -> Path:
    """Absolute path for a stored file, refusing anything outside the store.

    The value comes from a database column, and a column is still a path: a
    stored "../../backend/mplads.db" would otherwise serve the database. The
    same guard `serve_spa` applies to the built frontend.
    """
    root = config.UPLOAD_DIR.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise UploadError("Invalid photograph path.")
    return candidate
