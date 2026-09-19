"""Content-aware image triage and adaptive layout sizing.

Source decks mix genuinely informative visuals (architecture diagrams, screenshots,
data plots) with material that adds no documentary value and actively degrades a
published document: decorative vector clip-art, spacer rules, brand icons, and
personal headshots.

This module scores every candidate asset on cheap, deterministic signals and
returns an explicit include/exclude verdict plus a category. It also computes
display geometry that never upscales an asset beyond its native resolution, which
is what previously caused small clip-art to be blown up to half a page.

All analysis runs on a downsampled thumbnail, so cost is bounded and independent
of the source resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image, ImageOps

# Analysis is performed on a thumbnail so cost stays flat regardless of input size.
_THUMBNAIL_EDGE = 192
# Texture, however, is measured on a native-resolution centre crop.
_DETAIL_CROP_EDGE = 256

# An asset smaller than this in either dimension cannot carry readable detail.
MIN_DIMENSION_PX = 100
MIN_AREA_PX = 20_000

# Banner rules, dividers and sidebars have extreme aspect ratios.
MAX_ASPECT_RATIO = 6.0

# Flat vector art has very few distinct colours and almost no local texture.
DECORATIVE_MAX_COLORS = 24
DECORATIVE_MAX_DETAIL = 0.045
# Clip-art is typically exported with a large transparent margin.
DECORATIVE_MIN_TRANSPARENCY = 0.35

# Portrait photographs are excluded on privacy grounds, consistent with the
# roster-suppression policy already applied to extracted text.
PORTRAIT_MIN_SKIN_RATIO = 0.10
PORTRAIT_MIN_ASPECT = 0.5
PORTRAIT_MAX_ASPECT = 1.8
# Shading inside the skin region separates a face from flat orange artwork.
PORTRAIT_MIN_SKIN_VARIETY = 8

# Above this texture density an asset is treated as a diagram or screenshot.
DIAGRAM_MIN_DETAIL = 0.05

# Layout ceilings. A single figure must never dominate a page: at A4 the text
# frame is roughly 760pt tall, so 220pt keeps a figure under 30% of the page and
# leaves room for the surrounding narrative.
PDF_MAX_WIDTH_PT = 400.0
PDF_MAX_HEIGHT_PT = 220.0
DOCX_MAX_WIDTH_IN = 5.2
DOCX_MAX_HEIGHT_IN = 3.0
SOURCE_DPI = 96.0


@dataclass(frozen=True)
class ImageAssessment:
    """Verdict and measured features for a single candidate asset."""

    include: bool
    category: str
    reason: str
    width_px: int = 0
    height_px: int = 0
    detail_score: float = 0.0
    unique_colors: int = 0
    transparency_ratio: float = 0.0
    skin_ratio: float = 0.0

    @property
    def aspect_ratio(self) -> float:
        if self.height_px <= 0:
            return 0.0
        return self.width_px / self.height_px


def _transparency_ratio(image: Image.Image) -> float:
    """Fraction of pixels that are effectively transparent."""
    if image.mode not in ("RGBA", "LA", "PA") and "transparency" not in image.info:
        return 0.0
    alpha = image.convert("RGBA").getchannel("A")
    alpha.thumbnail((_THUMBNAIL_EDGE, _THUMBNAIL_EDGE))
    data = np.asarray(alpha, dtype=np.uint8)
    if data.size == 0:
        return 0.0
    return float(np.count_nonzero(data < 16) / data.size)


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    """Composite onto white so transparent clip-art is not scored as dark pixels."""
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(canvas, rgba).convert("RGB")
    return image.convert("RGB")


def _detail_score(rgb: Image.Image) -> float:
    """Mean normalised gradient magnitude: a proxy for edges, text and texture.

    This must be measured at native resolution. Downsampling averages away the
    high-frequency detail that distinguishes a screenshot from flat artwork.
    """
    gray = np.asarray(rgb.convert("L"), dtype=np.float32)
    if gray.size == 0 or min(gray.shape) < 2:
        return 0.0
    dy, dx = np.gradient(gray)
    magnitude = np.hypot(dx, dy)
    return float(np.clip(magnitude.mean() / 255.0, 0.0, 1.0))


def _center_crop(image: Image.Image, edge: int = _DETAIL_CROP_EDGE) -> Image.Image:
    """Native-resolution centre crop used for texture measurement."""
    width, height = image.size
    box_w, box_h = min(edge, width), min(edge, height)
    left = (width - box_w) // 2
    top = (height - box_h) // 2
    return image.crop((left, top, left + box_w, top + box_h))


def _unique_colors(rgb: Image.Image) -> int:
    """Distinct colours after coarse quantisation, ignoring compression noise."""
    data = np.asarray(rgb, dtype=np.uint8)
    if data.size == 0:
        return 0
    bucketed = (data // 24).reshape(-1, data.shape[-1])
    return int(np.unique(bucketed, axis=0).shape[0])


def _skin_stats(rgb: Image.Image) -> tuple[float, int]:
    """Return the skin-tone pixel fraction and the tonal variety within that region.

    The fraction alone is not a usable signal: orange and red corporate graphics
    satisfy the same RGB rule. Genuine faces additionally carry shading, so the
    skin region contains many distinct tones while flat artwork contains one.
    """
    data = np.asarray(rgb, dtype=np.int16)
    if data.size == 0 or data.ndim < 3 or data.shape[-1] < 3:
        return 0.0, 0
    r, g, b = data[..., 0], data[..., 1], data[..., 2]
    peak = data.max(axis=-1)
    trough = data.min(axis=-1)
    mask = (r > 95) & (g > 40) & (b > 20) & ((peak - trough) > 15) & (np.abs(r - g) > 15) & (r > g) & (r > b)
    ratio = float(np.count_nonzero(mask) / mask.size)
    if not np.any(mask):
        return ratio, 0
    skin_pixels = (data[mask] // 8).astype(np.uint8)
    variety = int(np.unique(skin_pixels, axis=0).shape[0])
    return ratio, variety


def image_dimensions(blob: bytes) -> tuple[int, int]:
    """Return native pixel dimensions, or (0, 0) if the asset cannot be read."""
    try:
        with Image.open(BytesIO(blob)) as image:
            return int(image.width), int(image.height)
    except Exception:
        return 0, 0


def assess_image(blob: bytes, *, exclude_person_photos: bool = True) -> ImageAssessment:
    """Classify an asset and decide whether it belongs in a published document."""
    try:
        with Image.open(BytesIO(blob)) as opened:
            oriented = ImageOps.exif_transpose(opened) or opened
            width, height = int(oriented.width), int(oriented.height)
            transparency = _transparency_ratio(oriented)
            flat = _flatten_to_rgb(oriented)
            detail_source = _center_crop(flat)
            thumb = flat.copy()
            thumb.thumbnail((_THUMBNAIL_EDGE, _THUMBNAIL_EDGE))
    except Exception:
        return ImageAssessment(False, "undecodable", "asset could not be decoded")

    if width <= 0 or height <= 0:
        return ImageAssessment(False, "undecodable", "zero-sized asset")

    if min(width, height) < MIN_DIMENSION_PX or (width * height) < MIN_AREA_PX:
        return ImageAssessment(
            False,
            "icon",
            "below the legible size threshold",
            width,
            height,
            transparency_ratio=transparency,
        )

    aspect = width / height
    if aspect > MAX_ASPECT_RATIO or aspect < (1.0 / MAX_ASPECT_RATIO):
        return ImageAssessment(
            False,
            "banner",
            "extreme aspect ratio indicates a rule or spacer",
            width,
            height,
            transparency_ratio=transparency,
        )

    detail = _detail_score(detail_source)
    colors = _unique_colors(thumb)
    skin, skin_variety = _skin_stats(thumb)

    features: dict[str, Any] = {
        "width_px": width,
        "height_px": height,
        "detail_score": round(detail, 4),
        "unique_colors": colors,
        "transparency_ratio": round(transparency, 4),
        "skin_ratio": round(skin, 4),
    }

    # The privacy rule is evaluated first: a smooth headshot would otherwise be
    # absorbed by the low-texture decorative rule and mislabelled.
    if (
        exclude_person_photos
        and skin >= PORTRAIT_MIN_SKIN_RATIO
        and skin_variety >= PORTRAIT_MIN_SKIN_VARIETY
        and PORTRAIT_MIN_ASPECT <= aspect <= PORTRAIT_MAX_ASPECT
        and detail < DIAGRAM_MIN_DETAIL
    ):
        return ImageAssessment(False, "portrait", "personal photograph withheld under the privacy policy", **features)

    is_flat = colors <= DECORATIVE_MAX_COLORS or transparency >= DECORATIVE_MIN_TRANSPARENCY
    if is_flat and detail < DECORATIVE_MAX_DETAIL:
        return ImageAssessment(
            False, "decorative", "flat, low-texture vector art carries no documentary detail", **features
        )

    category = "diagram" if detail >= DIAGRAM_MIN_DETAIL else "photo"
    return ImageAssessment(True, category, "informative visual retained", **features)


def display_size_pt(
    width_px: int,
    height_px: int,
    *,
    max_width_pt: float = PDF_MAX_WIDTH_PT,
    max_height_pt: float = PDF_MAX_HEIGHT_PT,
    source_dpi: float = SOURCE_DPI,
) -> tuple[float, float]:
    """Compute on-page geometry that fits the frame and never upscales the source.

    Returning the natural size for small assets is what stops low-resolution
    clip-art from being stretched across half a page.
    """
    if width_px <= 0 or height_px <= 0:
        return max_width_pt, max_height_pt

    natural_width = width_px * 72.0 / source_dpi
    natural_height = height_px * 72.0 / source_dpi
    scale = min(1.0, max_width_pt / natural_width, max_height_pt / natural_height)
    return natural_width * scale, natural_height * scale


def display_size_inches(
    width_px: int,
    height_px: int,
    *,
    max_width_in: float = DOCX_MAX_WIDTH_IN,
    max_height_in: float = DOCX_MAX_HEIGHT_IN,
) -> tuple[float, float]:
    """DOCX equivalent of :func:`display_size_pt`, expressed in inches."""
    width_pt, height_pt = display_size_pt(
        width_px,
        height_px,
        max_width_pt=max_width_in * 72.0,
        max_height_pt=max_height_in * 72.0,
    )
    return width_pt / 72.0, height_pt / 72.0
