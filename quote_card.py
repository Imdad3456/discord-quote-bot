import io
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "assets", "fonts")
FONT_BOLD = os.path.join(FONT_DIR, "Poppins-Bold.ttf")
FONT_REGULAR = os.path.join(FONT_DIR, "Poppins-Regular.ttf")
FONT_ITALIC = os.path.join(FONT_DIR, "Poppins-Italic.ttf")

WIDTH, HEIGHT = 1200, 630
AVATAR_WIDTH = int(WIDTH * 0.36)
TEXT_BOX = (80, 80, WIDTH - AVATAR_WIDTH - 60, HEIGHT - 80)  # left, top, right, bottom
BG_COLOR = (0, 0, 0)
TEXT_COLOR = (235, 235, 235)
NAME_COLOR = (235, 235, 235)


def _wrap_text(draw, text, font, max_width):
    words = text.split()
    if not words:
        return [""]
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _fit_quote_text(draw, text, max_width, max_height):
    for size in (72, 64, 56, 48, 40, 34, 28, 24):
        font = ImageFont.truetype(FONT_BOLD, size)
        lines = _wrap_text(draw, text, font, max_width)
        line_height = int(size * 1.25)
        total_height = line_height * len(lines)
        if total_height <= max_height:
            return font, lines, line_height
    # Fall back to smallest size, truncating lines that don't fit.
    font = ImageFont.truetype(FONT_BOLD, 24)
    lines = _wrap_text(draw, text, font, max_width)
    line_height = int(24 * 1.25)
    max_lines = max(1, max_height // line_height)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip() + "..."
    return font, lines, line_height


def _prep_avatar(avatar_bytes, box_width, box_height):
    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGB")
    src_w, src_h = avatar.size
    target_ratio = box_width / box_height
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        new_w = int(src_h * target_ratio)
        offset = (src_w - new_w) // 2
        avatar = avatar.crop((offset, 0, offset + new_w, src_h))
    else:
        new_h = int(src_w / target_ratio)
        offset = (src_h - new_h) // 2
        avatar = avatar.crop((0, offset, src_w, offset + new_h))
    return avatar.resize((box_width, box_height), Image.LANCZOS)


def render_quote_card(quote_text, display_name, avatar_bytes):
    """Render a quote card image and return it as a BytesIO PNG buffer."""
    card = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)

    avatar = _prep_avatar(avatar_bytes, AVATAR_WIDTH, HEIGHT)
    card.paste(avatar, (WIDTH - AVATAR_WIDTH, 0))

    # Soft gradient seam so the avatar blends into the background instead of a hard edge.
    blend_width = 240
    seam_x = WIDTH - AVATAR_WIDTH
    gradient = Image.new("L", (blend_width, HEIGHT), 0)
    grad_draw = ImageDraw.Draw(gradient)
    for i in range(blend_width):
        t = i / blend_width
        eased = t * t * (3 - 2 * t)  # smoothstep - gradual at both ends, not a linear ramp
        alpha = int(255 * (1 - eased))
        grad_draw.line([(i, 0), (i, HEIGHT)], fill=alpha)
    gradient = gradient.filter(ImageFilter.GaussianBlur(8))
    bg_strip = Image.new("RGB", (blend_width, HEIGHT), BG_COLOR)
    card.paste(bg_strip, (seam_x - blend_width // 2, 0), gradient)

    draw = ImageDraw.Draw(card)

    left, top, right, bottom = TEXT_BOX
    max_width = right - left

    name_font = ImageFont.truetype(FONT_ITALIC, 30)
    footer_height = 8 + 30  # gap + name line

    quote_font, lines, line_height = _fit_quote_text(
        draw, f"“{quote_text}”", max_width, bottom - top - footer_height
    )

    total_quote_height = line_height * len(lines)
    text_block_height = total_quote_height + footer_height
    y = top + max(0, (bottom - top - text_block_height) // 2)

    for line in lines:
        draw.text((left, y), line, font=quote_font, fill=TEXT_COLOR)
        y += line_height

    y += 8
    draw.text((left, y), f"— {display_name}", font=name_font, fill=NAME_COLOR)

    buffer = io.BytesIO()
    card.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
