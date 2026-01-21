from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance
import aiohttp
import io
import os
import pathlib
import asyncio
from datetime import datetime

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
    img = char_data.get('image_obj')
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

    # FIX: Fetch all images concurrently to prevent timeouts/stuck commands
    tasks = [fetch_image(char['image_url']) for char in character_list]
    downloaded_images = await asyncio.gather(*tasks)
    for i, img in enumerate(downloaded_images):
        character_list[i]['image_obj'] = img

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


async def generate_team_image(team_list):
    """
    Draws the 5-Stack Team Banner with a flat black background and detailed stats.
    team_list: List of dicts containing 'name', 'power', 'ability_tags', etc.
    """
    # 1. Canvas Setup (Wide Banner - increased height for stats)
    canvas_w, canvas_h = 1200, 550
    # Flat Black Background as requested
    base_img = Image.new("RGBA", (canvas_w, canvas_h), (10, 10, 10, 255))
    draw = ImageDraw.Draw(base_img)

    # 2. Fonts
    try:
        font_large = ImageFont.truetype(str(FONT_PATH), 45)
        font_medium = ImageFont.truetype(str(FONT_PATH), 26)
        font_small = ImageFont.truetype(str(FONT_PATH), 18)
    except:
        font_large = font_medium = font_small = ImageFont.load_default()

    # 3. Total Power Calculation & Header
    total_power = sum(char['power'] for char in team_list if char)
    header_text = f"SQUAD TOTAL POWER: {total_power:,}"
    
    # Center the header
    bbox = draw.textbbox((0, 0), header_text, font=font_large)
    tx_w = bbox[2] - bbox[0]
    draw.text(((canvas_w - tx_w) / 2, 25), header_text, font=font_large, fill="#FFD700")

    # 4. Fetch Images concurrently
    tasks = []
    indices = []
    for i, char in enumerate(team_list):
        if char:
            tasks.append(fetch_image(char['image_url']))
            indices.append(i)
    
    if tasks:
        downloaded = await asyncio.gather(*tasks)
        for i, img in zip(indices, downloaded):
            team_list[i]['image_obj'] = img

    # 5. Layout (200x300 cards + gap)
    start_x = 70
    start_y = 100 
    gap_x = 15

    for i, char in enumerate(team_list):
        x = start_x + (i * (200 + gap_x))
        y = start_y

        if char:
            # Draw the Card
            card = create_character_card(char)
            base_img.paste(card, (x, y), card)
            
            # Draw Individual Power
            p_text = f"⚔️ {char['power']:,}"
            p_bbox = draw.textbbox((0, 0), p_text, font=font_medium)
            px_w = p_bbox[2] - p_bbox[0]
            draw.text((x + (200 - px_w) / 2, y + 310), p_text, font=font_medium, fill="white")
            
            # Draw Skills
            skills = char.get('ability_tags', [])
            s_text = ", ".join(skills) if skills else "No Skills"
            s_color = "#AAAAAA" if not skills else "#00FF7F" # Gray for none, Green for active
            s_bbox = draw.textbbox((0, 0), s_text, font=font_small)
            sx_w = s_bbox[2] - s_bbox[0]
            draw.text((x + (200 - sx_w) / 2, y + 345), s_text, font=font_small, fill=s_color)
            
        else:
            # Draw "Empty Slot" Placeholder
            empty_slot = Image.new("RGBA", (200, 300), (30, 30, 30, 255))
            e_draw = ImageDraw.Draw(empty_slot)
            e_draw.rectangle([0, 0, 199, 299], outline="#444444", width=2)
            
            text = f"SLOT {i + 1}"
            bbox = e_draw.textbbox((0, 0), text, font=font_medium)
            tx_w, tx_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            e_draw.text(((200 - tx_w) / 2, (300 - tx_h) / 2), text, font=font_medium, fill="#666666")
            base_img.paste(empty_slot, (x, y), empty_slot)

    # 6. Save
    output = io.BytesIO()
    base_img.save(output, format="PNG")
    output.seek(0)
    return output


async def generate_banner_image(character_data_list, banner_name, end_timestamp):
    """
    Creates a banner image featuring rate-up units and the expiration date.
    """
    banner_w, banner_h = 800, 450 # Increased height slightly for better text spacing
    canvas = Image.new('RGB', (banner_w, banner_h), (20, 20, 20))
    
    num_chars = len(character_data_list)
    strip_w = banner_w // num_chars

    async with aiohttp.ClientSession() as session:
        for i, char in enumerate(character_data_list):
            async with session.get(char['image_url']) as resp:
                if resp.status == 200:
                    img_data = await resp.read()
                    char_img = Image.open(io.BytesIO(img_data)).convert("RGBA")
                    
                    # Resize and Crop logic
                    aspect = char_img.width / char_img.height
                    target_h = banner_h
                    target_w = int(target_h * aspect)
                    char_img = char_img.resize((target_w, target_h), Image.LANCZOS)
                    
                    left = (char_img.width - strip_w) // 2
                    char_img = char_img.crop((left, 0, left + strip_w, banner_h))
                    
                    canvas.paste(char_img, (i * strip_w, 0), char_img)

    # UI Overlay
    draw = ImageDraw.Draw(canvas)
    # Path from your project assets
    font_bold = ImageFont.truetype("assets/fonts/bold_font.ttf", 45)
    font_small = ImageFont.truetype("assets/fonts/bold_font.ttf", 25)
    
    # Semi-transparent footer
    overlay_h = 100
    draw.rectangle([0, banner_h - overlay_h, banner_w, banner_h], fill=(0, 0, 0, 180))
    
    # Title: Rate Up Name
    draw.text((20, banner_h - 90), f"RATE UP: {banner_name.upper()}", font=font_bold, fill=(255, 215, 0))
    
    # Subtitle: Expiration Date
    expiry_str = datetime.fromtimestamp(end_timestamp).strftime("%b %d, %Y - %H:%M")
    draw.text((22, banner_h - 35), f"ENDS: {expiry_str} UTC", font=font_small, fill=(200, 200, 200))

    out = io.BytesIO()
    canvas.save(out, format="PNG")
    out.seek(0)
    return out