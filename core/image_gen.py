from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance
import aiohttp
import io
import os
import pathlib

# --- ROBUST PATH SETUP ---
# Gets the absolute path of the folder this script is in
current_dir = pathlib.Path(__file__).parent.absolute()
project_root = current_dir.parent

# Builds absolute paths to assets
FONT_PATH = project_root / "assets" / "fonts" / "bold_font.ttf"
BG_PATH = project_root / "assets" / "templates" / "gacha_bg.jpg"

# Rarity Theme Colors
THEMES = {
    "SSR": {
        "hex": "#FFD700",
        "rgb": (255, 215, 0)
    },
    "SR": {
        "hex": "#DA70D6",
        "rgb": (218, 112, 214)
    },
    "R": {
        "hex": "#00BFFF",
        "rgb": (0, 191, 255)
    }
}


async def fetch_image(url):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return Image.open(io.BytesIO(data)).convert("RGBA")
        except:
            pass
    return None


def get_fitted_font(draw, text, max_width, font_path, max_font_size=40):
    """
    Starts at Size 40 and shrinks until the text fits the box width.
    """
    size = max_font_size
    while size > 10:
        try:
            font = ImageFont.truetype(str(font_path), size)
        except OSError:
            # FONT FILE MISSING - RETURN DEFAULT AND PRINT ERROR
            print(f"❌ CRITICAL: Font file not found at {font_path}")
            return ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]

        if text_width <= max_width:
            return font

        size -= 2  # Shrink step

    return ImageFont.truetype(str(font_path), 10)


def apply_holo_effect(img, rarity):
    if rarity == "R": return img
    img = ImageEnhance.Color(img).enhance(1.3 if rarity == "SSR" else 1.15)
    img = ImageEnhance.Contrast(img).enhance(1.1)
    overlay_color = THEMES[rarity]["rgb"]
    overlay = Image.new("RGBA", img.size, overlay_color)
    img = Image.blend(img.convert("RGB"), overlay.convert("RGB"),
                      0.1).convert("RGBA")
    return img


def create_character_card(char_data, card_size=(200, 300)):
    card = Image.new("RGBA", card_size, (20, 20, 20, 255))
    draw = ImageDraw.Draw(card)
    theme = THEMES.get(char_data['rarity'], THEMES["R"])

    # Image
    img = char_data['image_obj']
    if img:
        img = ImageOps.fit(img, (card_size[0], card_size[1] - 50),
                           method=Image.Resampling.LANCZOS)
        img = apply_holo_effect(img, char_data['rarity'])
        card.paste(img, (0, 0))

    # Text Box
    draw.rectangle([0, 250, 200, 300], fill="#151515")
    draw.rectangle([0, 250, 200, 254], fill=theme["hex"])

    # --- NAME SCALING LOGIC ---
    name = char_data['name']

    # Get a font that fits perfectly inside 190px (leaving 5px padding on each side)
    font_name = get_fitted_font(draw, name, 190, FONT_PATH, max_font_size=36)

    # Center Calculations
    bbox = draw.textbbox((0, 0), name, font=font_name)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x_pos = (200 - text_width) / 2
    # Vertical Center of the 50px box (starting at 250)
    y_pos = 250 + (50 - text_height) / 2 - 4

    draw.text((x_pos, y_pos), name, font=font_name, fill="white")

    # Rarity Tag
    try:
        font_bold = ImageFont.truetype(str(FONT_PATH), 24)
    except:
        font_bold = ImageFont.load_default()

    rarity_text = char_data['rarity']
    text_x, text_y = 8, 5
    draw.text((text_x + 2, text_y + 2),
              rarity_text,
              font=font_bold,
              fill="black")
    draw.text((text_x, text_y), rarity_text, font=font_bold, fill=theme["hex"])
    draw.text((text_x, text_y),
              rarity_text,
              font=font_bold,
              fill=theme["hex"],
              stroke_width=1,
              stroke_fill="white")

    # Border
    border_width = 5 if char_data['rarity'] != "R" else 2
    border_color = theme["hex"] if char_data['rarity'] != "R" else "#333333"
    draw.rectangle([0, 0, 199, 299], outline=border_color, width=border_width)

    return card


async def generate_10_pull_image(character_list):
    canvas_w, canvas_h = 1100, 700
    try:
        base_img = Image.open(str(BG_PATH)).convert("RGBA").resize(
            (canvas_w, canvas_h))
    except:
        print(f"⚠️ Warning: BG not found at {BG_PATH}")
        base_img = Image.new("RGBA", (canvas_w, canvas_h), "#121212")

    for char in character_list:
        char['image_obj'] = await fetch_image(char['image_url'])

    start_x, start_y = 40, 40
    gap_x, gap_y = 10, 20

    for i, char in enumerate(character_list):
        card = create_character_card(char)
        row = i // 5
        col = i % 5
        x = start_x + (col * (200 + gap_x))
        y = start_y + (row * (300 + gap_y))
        base_img.paste(card, (x, y), card)

    output = io.BytesIO()
    base_img.save(output, format="PNG")
    output.seek(0)
    return output


# ... (Keep all your existing imports and functions)


async def generate_team_image(team_list):
    """
    Draws the 5-Stack Team Banner.
    team_list: A list of 5 dictionaries. If a slot is empty, the dict is None.
    """
    # 1. Canvas Setup (Wide Banner)
    canvas_w, canvas_h = 1200, 450
    try:
        # You can add a specific 'team_bg.jpg' later if you want a different vibe
        base_img = Image.open(str(BG_PATH)).convert("RGBA").resize(
            (canvas_w, canvas_h))
    except:
        base_img = Image.new("RGBA", (canvas_w, canvas_h), "#101010")

    # Darken the background slightly so characters pop
    overlay = Image.new("RGBA", base_img.size, (0, 0, 0, 100))
    base_img = Image.alpha_composite(base_img, overlay)

    # 2. Fetch Images for existing members
    for char in team_list:
        if char:
            char['image_obj'] = await fetch_image(char['image_url'])

    # 3. Layout: A tight row of 5 centered cards
    # Card size: 200x300
    # Spacing: 15px
    # Total Width: (200 * 5) + (15 * 4) = 1060px
    # Start X: (1200 - 1060) / 2 = 70px
    start_x = 70
    start_y = 75  # Vertically centered-ish
    gap_x = 15

    # 4. Drawing Loop
    for i, char in enumerate(team_list):
        x = start_x + (i * (200 + gap_x))
        y = start_y

        if char:
            # Draw the Card
            card = create_character_card(char)
            base_img.paste(card, (x, y), card)
        else:
            # Draw "Empty Slot" Placeholder
            # Create a semi-transparent gray box
            empty_slot = Image.new("RGBA", (200, 300), (50, 50, 50, 100))
            draw = ImageDraw.Draw(empty_slot)

            # Dashed Border
            draw.rectangle([0, 0, 199, 299], outline="#666666", width=2)

            # "EMPTY" Text
            try:
                font = ImageFont.truetype(str(FONT_PATH), 24)
            except:
                font = ImageFont.load_default()

            text = "SLOT " + str(i + 1)
            bbox = draw.textbbox((0, 0), text, font=font)
            tx_w = bbox[2] - bbox[0]
            tx_h = bbox[3] - bbox[1]

            draw.text(((200 - tx_w) / 2, (300 - tx_h) / 2),
                      text,
                      font=font,
                      fill="#999999")

            base_img.paste(empty_slot, (x, y), empty_slot)

    # 5. Save
    output = io.BytesIO()
    base_img.save(output, format="PNG")
    output.seek(0)
    return output
