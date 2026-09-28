"""Build Android and web branding from resources/logo-source.png (Pillow required)."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

MOBILE = Path(__file__).resolve().parents[1]
RESOURCES = MOBILE / "resources"
ANDROID_RES = MOBILE / "android" / "app" / "src" / "main" / "res"
BACKGROUND = (2, 25, 89)
DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}


def save(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def remove_background(source: Image.Image) -> Image.Image:
    # The supplied artwork has a navy background (blue channel <= 92) and
    # blue/cyan/white foreground. A soft matte preserves anti-aliased edges.
    alpha = source.getchannel("B").point(
        lambda value: max(0, min(255, (value - 112) * 255 // 32)),
    )
    result = source.convert("RGBA")
    result.putalpha(alpha)
    return result


def crop_visible(image: Image.Image) -> Image.Image:
    bounds = image.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("The supplied logo has no visible foreground")
    return image.crop(bounds)


def centered_mark(symbol: Image.Image, size: int, radius_fraction: float) -> Image.Image:
    alpha = symbol.getchannel("A")
    pixels = alpha.load()
    center_x, center_y = (symbol.width - 1) / 2, (symbol.height - 1) / 2
    radius = max(
        math.hypot(x - center_x, y - center_y)
        for y in range(symbol.height)
        for x in range(symbol.width)
        if pixels[x, y]
    )
    scale = size * radius_fraction / radius
    resized = symbol.resize(
        (max(1, round(symbol.width * scale)), max(1, round(symbol.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (size, size))
    canvas.alpha_composite(
        resized, ((size - resized.width) // 2, (size - resized.height) // 2),
    )
    return canvas


def generate() -> None:
    source = Image.open(RESOURCES / "logo-source.png").convert("RGB")
    foreground = remove_background(source)
    lockup = crop_visible(foreground)
    # The symbol is above the wordmark in this supplied image.
    symbol = crop_visible(
        foreground.crop((0, 0, source.width, round(source.height * 0.61))),
    )

    web_logo = Image.new("RGBA", (900, 660))
    fitted = ImageOps.contain(lockup, (864, 624), Image.Resampling.LANCZOS)
    web_logo.alpha_composite(
        fitted, ((web_logo.width - fitted.width) // 2, (web_logo.height - fitted.height) // 2),
    )
    save(web_logo, MOBILE / "src" / "assets" / "brand-logo.png")

    store_icon = Image.new("RGBA", (512, 512), BACKGROUND + (255,))
    store_icon.alpha_composite(centered_mark(symbol, 512, 0.40))
    save(store_icon.convert("RGB"), RESOURCES / "rustore-icon-512.png")

    for density, factor in DENSITIES.items():
        directory = ANDROID_RES / ("mipmap-" + density)
        size = round(48 * factor)
        icon = Image.new("RGBA", (size, size), BACKGROUND + (255,))
        icon.alpha_composite(centered_mark(symbol, size, 0.40))
        rounded = Image.new("L", (size * 4, size * 4))
        ImageDraw.Draw(rounded).rounded_rectangle(
            (0, 0, size * 4 - 1, size * 4 - 1), radius=size * 0.8, fill=255,
        )
        icon.putalpha(rounded.resize((size, size), Image.Resampling.LANCZOS))
        save(icon, directory / "ic_launcher.png")
        circle = Image.new("L", (size * 4, size * 4))
        ImageDraw.Draw(circle).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
        icon.putalpha(circle.resize((size, size), Image.Resampling.LANCZOS))
        save(icon, directory / "ic_launcher_round.png")

        # Adaptive artwork stays within a 63.7dp circle on the 108dp canvas,
        # inside Android's 66dp safe zone, regardless of the launcher mask.
        adaptive = centered_mark(symbol, round(108 * factor), 0.295)
        save(adaptive, directory / "ic_launcher_foreground.png")
        monochrome = Image.new("RGBA", adaptive.size, (255, 255, 255, 0))
        monochrome.putalpha(adaptive.getchannel("A"))
        save(monochrome, directory / "ic_launcher_monochrome.png")

        # A centered bitmap inside splash.xml preserves the logo's proportions
        # on every screen instead of stretching a full-screen PNG.
        splash_logo = web_logo.resize(
            (round(216 * factor), round(216 * 660 / 900 * factor)),
            Image.Resampling.LANCZOS,
        )
        save(splash_logo, ANDROID_RES / ("drawable-" + density) / "buildvision_splash_logo.png")

    # Retire only the known template assets replaced by this generator.
    obsolete = [
        ANDROID_RES / "drawable" / "splash.png",
        ANDROID_RES / "drawable" / "ic_launcher_background.xml",
        ANDROID_RES / "drawable-v24" / "ic_launcher_foreground.xml",
    ]
    obsolete.extend(
        ANDROID_RES / f"drawable-{orientation}-{density}" / "splash.png"
        for orientation in ("land", "port") for density in DENSITIES
    )
    for file in obsolete:
        file.unlink(missing_ok=True)

    print("Generated launcher icons, themed icons, splash screens, login logo and RuStore icon.")


if __name__ == "__main__":
    generate()
