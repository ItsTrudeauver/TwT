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
            import json
            skills = char.get('ability_tags', [])
            
            # Robustly handle string vs list and empty arrays
            if isinstance(skills, str):
                try:
                    skills = json.loads(skills)
                except:
                    # If it's a raw string like "surge", wrap it in a list
                    skills = [skills] if skills.strip() else []
            
            # Clean up empty elements and format for display
            active_skills = [str(s).capitalize() for s in skills if s and str(s).strip()]
            
            s_text = ", ".join(active_skills) if active_skills else "No Skills"
            s_color = "#AAAAAA" if not active_skills else "#00FF7F"
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

async def generate_battle_image(team1, team2, name1, name2, winner_idx=None):
    """
    Generates a VS screen.
    winner_idx: 0 = Draw, 1 = Team 1 Wins, 2 = Team 2 Wins.
    """
    # 1. Setup Canvas (Balanced Height/Width for stacking)
    W, H = 1200, 850
    canvas = Image.new("RGBA", (W, H), (15, 15, 15, 255))
    draw = ImageDraw.Draw(canvas)
    
    # 2. Helper to fetch and prep cards
    async def prep_team_cards(team_list, is_right_side=False):
        tasks = []
        for char in team_list:
            if char.get('image_url'):
                tasks.append(fetch_image(char['image_url']))
            else:
                # Placeholder for NPCs with no image
                tasks.append(asyncio.sleep(0, result=None)) # Return None immediately
        
        images = await asyncio.gather(*tasks)
        cards = []
        for i, img in enumerate(images):
            # Inject image object back into data for card creator
            team_list[i]['image_obj'] = img
            card = create_character_card(team_list[i])
            
            # Mirror enemies to face the player
            if is_right_side:
                card = ImageOps.mirror(card)
            
            cards.append(card)
        return cards

    # 3. Process Teams Concurrently
    cards1, cards2 = await asyncio.gather(
        prep_team_cards(team1, is_right_side=False),
        prep_team_cards(team2, is_right_side=True)
    )

    # 4. Layout Constants (Grid-style positioning)
    card_w, card_h = 200, 300
    gap = 20
    start_x = (W - (5 * card_w + 4 * gap)) // 2
    
    # Draw Team 1 (Attacker - Top Row)
    for i, card in enumerate(cards1):
        x = start_x + (i * (card_w + gap))
        y = 100
        if winner_idx == 2: card = ImageOps.grayscale(card)
        canvas.paste(card, (x, y), card)

    # Draw Team 2 (Defender - Bottom Row)
    for i, card in enumerate(cards2):
        x = start_x + (i * (card_w + gap))
        y = 500
        if winner_idx == 1: card = ImageOps.grayscale(card)
        canvas.paste(card, (x, y), card)

    # 5. Overlay & VS Text
    try:
        font_vs = ImageFont.truetype(str(FONT_PATH), 120)
        font_name = ImageFont.truetype(str(FONT_PATH), 45)
    except:
        font_vs = font_name = ImageFont.load_default()

    # Central VS Logo
    vs_text = "V S"
    v_bbox = draw.textbbox((0, 0), vs_text, font=font_vs)
    v_w = v_bbox[2] - v_bbox[0]
    draw.text(((W - v_w) // 2, 400), vs_text, font=font_vs, fill="#FF4500", stroke_width=2, stroke_fill="white")
    
    # Names positioned near their respective teams
    draw.text((start_x, 40), f"PLAYER: {name1.upper()}", font=font_name, fill="cyan")
    
    bbox2 = draw.textbbox((0, 0), f"OPPONENT: {name2.upper()}", font=font_name)
    n2_w = bbox2[2] - bbox2[0]
    draw.text((W - start_x - n2_w, 440), f"OPPONENT: {name2.upper()}", font=font_name, fill="orange")

    # 6. Save
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    out.seek(0)
    return out