"""Local image inspection and lightweight manipulation triage."""

import io
from pathlib import Path

from PIL import Image, ImageChops, ImageStat, UnidentifiedImageError

MAX_IMAGE_PIXELS = 40_000_000


class ImageInspectionError(ValueError):
    """The supplied file could not be decoded as a supported image."""


def inspect_image(path: Path) -> dict[str, object]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ImageInspectionError(
                    f"Image exceeds the {MAX_IMAGE_PIXELS:,}-pixel processing limit."
                )
            return {
                "format": image.format,
                "width": image.width,
                "height": image.height,
                "mode": image.mode,
                "exif_fields": len(image.getexif()),
            }
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageInspectionError("The upload is not a readable image.") from exc


def manipulation_signals(path: Path) -> dict[str, object]:
    """Return forensic indicators, never a claim that an image is fraudulent."""
    metadata = inspect_image(path)
    signals: list[str] = []
    ela_score: float | None = None
    with Image.open(path) as source:
        image = source.convert("RGB")
        if metadata["exif_fields"] == 0:
            signals.append("No EXIF metadata is present (common after export or messaging apps).")
        if source.format == "JPEG":
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=90)
            buffer.seek(0)
            with Image.open(buffer) as recompressed:
                difference = ImageChops.difference(image, recompressed.convert("RGB"))
                ela_score = round(sum(ImageStat.Stat(difference).mean) / 3, 3)
                if ela_score > 12:
                    signals.append(
                        "Elevated JPEG recompression difference; inspect edited regions manually."
                    )
        else:
            signals.append("ELA is unavailable because this is not a JPEG image.")
    return {"metadata": metadata, "ela_score": ela_score, "signals": signals}
