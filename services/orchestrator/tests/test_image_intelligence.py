from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.image_intelligence import (
    assess_image,
    display_size_inches,
    display_size_pt,
    image_dimensions,
)


def _encode(image: Image.Image, fmt: str = "PNG") -> bytes:
    buffer = BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def _flat_shape(size=(600, 600)) -> bytes:
    """Solid vector-style clip-art on a transparent canvas."""
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    block = Image.new("RGBA", (size[0] // 2, size[1] // 2), (230, 120, 80, 255))
    canvas.paste(block, (size[0] // 4, size[1] // 4))
    return _encode(canvas)


def _textured_diagram(size=(600, 400)) -> bytes:
    """Boxes, connectors and text-like marks standing in for an architecture diagram."""
    canvas = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    step = max(12, min(size) // 8)
    for x in range(0, size[0], step):
        draw.line([(x, 0), (x, size[1])], fill=(20, 40, 90), width=2)
    for y in range(0, size[1], step):
        draw.line([(0, y), (size[0], y)], fill=(200, 60, 30), width=2)
    for x in range(0, size[0], step * 2):
        draw.rectangle([x + 2, 2, x + step - 2, size[1] - 2], outline=(0, 0, 0), width=1)
    return _encode(canvas)


def _skin_toned_portrait(size=(400, 500)) -> bytes:
    """Smooth, softly shaded skin-toned field approximating a headshot.

    Real faces carry tonal variation across the skin region, which is the signal
    the classifier uses to tell a photograph from flat orange artwork.
    """
    xs = np.linspace(0, 1, size[0], dtype=np.float32)[None, :]
    ys = np.linspace(0, 1, size[1], dtype=np.float32)[:, None]
    shading = (np.sin(xs * 3.1) * np.cos(ys * 2.7) + 1.0) / 2.0

    red = 150 + shading * 100
    green = 95 + shading * 75
    blue = 70 + shading * 60
    stacked = np.stack([red, green, blue], axis=-1)
    return _encode(Image.fromarray(np.clip(stacked, 0, 255).astype(np.uint8), mode="RGB"))


def test_decorative_clipart_is_suppressed():
    verdict = assess_image(_flat_shape())

    assert verdict.include is False
    assert verdict.category == "decorative"


def test_textured_diagram_is_retained():
    verdict = assess_image(_textured_diagram())

    assert verdict.include is True
    assert verdict.category == "diagram"


def test_small_icon_is_suppressed():
    verdict = assess_image(_textured_diagram(size=(64, 64)))

    assert verdict.include is False
    assert verdict.category == "icon"


def test_banner_aspect_ratio_is_suppressed():
    verdict = assess_image(_textured_diagram(size=(1200, 120)))

    assert verdict.include is False
    assert verdict.category == "banner"


def test_portrait_photograph_is_suppressed_for_privacy():
    verdict = assess_image(_skin_toned_portrait())

    assert verdict.include is False
    assert verdict.category == "portrait"
    assert verdict.skin_ratio > 0


def test_portrait_can_be_retained_when_policy_disabled():
    verdict = assess_image(_skin_toned_portrait(), exclude_person_photos=False)

    assert verdict.category != "portrait"


def test_undecodable_asset_is_reported_not_raised():
    verdict = assess_image(b"not an image at all")

    assert verdict.include is False
    assert verdict.category == "undecodable"


def test_image_dimensions_reads_native_size():
    assert image_dimensions(_textured_diagram(size=(640, 480))) == (640, 480)
    assert image_dimensions(b"corrupt") == (0, 0)


def test_small_images_are_never_upscaled():
    # A 96x96 source is 72pt at 96 DPI and must stay 72pt, not fill the frame.
    width, height = display_size_pt(96, 96, max_width_pt=430, max_height_pt=300)

    assert width == 72.0
    assert height == 72.0


def test_large_images_are_clamped_to_the_frame():
    width, height = display_size_pt(4000, 3000, max_width_pt=430, max_height_pt=300)

    assert width <= 430.0
    assert height <= 300.0
    # Aspect ratio is preserved through the clamp.
    assert round(width / height, 3) == round(4000 / 3000, 3)


def test_tall_images_are_bounded_by_height_not_width():
    width, height = display_size_pt(1000, 4000, max_width_pt=430, max_height_pt=300)

    assert height <= 300.0
    assert width < 430.0


def test_display_size_inches_matches_point_geometry():
    width_in, height_in = display_size_inches(4000, 3000, max_width_in=5.8, max_height_in=4.0)

    assert width_in <= 5.8
    assert height_in <= 4.0


def test_display_size_handles_unknown_dimensions():
    assert display_size_pt(0, 0, max_width_pt=430, max_height_pt=300) == (430, 300)
