# Draws the background of the orch Companion install window (ORCH-1497): title, what it does, a thin arrow from
# the app to Applications, and the one thing to do. Run once after a change of words or layout; the pictures are
# kept in git so a release needs no drawing library:
#   uv run --with pillow==11.3.0 python companion/mac/dmg_background.py
# Positions match icon_locations in dmg_settings.py (window 600 x 380, icons centred at y 190).
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONT = "/System/Library/Fonts/SFNS.ttf"


def draw(scale: int) -> Image.Image:
    s = scale
    img = Image.new("RGB", (600 * s, 380 * s), (255, 255, 255))
    d = ImageDraw.Draw(img)
    title = ImageFont.truetype(FONT, 24 * s)
    title.set_variation_by_name("Semibold")
    small = ImageFont.truetype(FONT, 13 * s)
    d.text((300 * s, 48 * s), "orch Companion", fill=(20, 20, 20), font=title, anchor="mm")
    d.text((300 * s, 78 * s), "Records your calls for Meetings", fill=(110, 110, 110), font=small, anchor="mm")
    # arrow between the two icons (app at x 150, Applications at x 450)
    y, x0, x1 = 190 * s, 245 * s, 355 * s
    d.line((x0, y, x1, y), fill=(40, 40, 40), width=2 * s)
    d.line((x1 - 14 * s, y - 14 * s, x1, y, x1 - 14 * s, y + 14 * s), fill=(40, 40, 40), width=2 * s, joint="curve")
    d.text((300 * s, 338 * s), "Drag orch Companion to Applications", fill=(110, 110, 110), font=small, anchor="mm")
    return img


if __name__ == "__main__":
    draw(1).save(HERE / "dmg-background.png", dpi=(72, 72))
    draw(2).save(HERE / "dmg-background@2x.png", dpi=(144, 144))
