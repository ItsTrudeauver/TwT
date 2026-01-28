from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance
import aiohttp
import io
import os
import pathlib
import asyncio
from datetime import datetime

# --- ROBUST PATH SETUP ---
current_dir = pathlib.Path(__file__).parent.absolute()
project_root = current_dir.parent

FONT_PATH = project_root / "assets" / "fonts" / "bold_font.ttf"
BG_PATH = project_root / "assets" / "templates" / "gacha_bg.jpg"

# Star Colors
STAR_YELLOW = (255, 215, 0)
STAR_RED = (255, 69, 0)

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


async def fetch_image(session, url):
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.read()
                return Image.open(io.BytesIO(data)).convert("RGBA")
    except:
        pass
    return None


def get_fitted_font(draw, text, max_width, font_path, max_font_size=40):
    size = max_font_size
    while size > 10:
        try:
            font = ImageFont.truetype(str(font_path), size)
        except OSError:
            print(f"❌ CRITICAL: Font file not found at {font_path}")
            return ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]

        if text_width <= max_width:
            return font

        size -= 2

    return ImageFont.truetype(str(font_path), 10)


def apply_holo_effect(img, rarity):
    if rarity == "R": return img
    
    if rarity == "SR":
        img = ImageEnhance.Color(img).enhance(1.2)
        overlay = Image.new("RGBA", img.size, THEMES["SR"]["rgb"] + (40,))
        return Image.alpha_composite(img.convert("RGBA"), overlay)

    if rarity == "SSR":
        img = ImageEnhance.Color(img).enhance(1.6)
        img = ImageEnhance.Contrast(img).enhance(1.15)
        img = img.convert("RGBA")

        rainbow = Image.new("RGBA", img.size)
        draw = ImageDraw.Draw(rainbow)
        
        for i in range(img.width + img.height):
            hue = int((i / (img.width + img.height)) * 255)
            if hue < 85: r, g, b = 255, hue * 3, 0
            elif hue < 170: r, g, b = 255 - (hue - 85) * 3, 255, 0
            else: r, g, b = 0, 255, (hue - 170) * 3
            
            draw.line([(i, 0), (0, i)], fill=(r, g, b, 45), width=2)
            
        return Image.alpha_composite(img, rainbow)
    
    return img


def draw_dupe_stars(draw, dupe_level, card_width):
    """
    Draws stars based on the 'Lap' logic:
    - 1-5 dupes: 1-5 yellow stars.
    - 6-10 dupes: 5 stars total, where (dupe - 5) are Red and the rest are Yellow.
    """
    if not dupe_level or dupe_level <= 0:
        return

    # Determine counts based on 'Lap' logic (max 5 slots)
    if dupe_level <= 5:
        red_count = 0
        yellow_count = dupe_level
    else:
        # Lap 2: Red stars (capped at 5)
        red_count = min(5, dupe_level - 5)
        # Remaining slots are yellow (to make a total of 5 stars)
        yellow_count = 5 - red_count

    total_stars = red_count + yellow_count
    star_size = 12
    gap = 2
    
    # Center stars horizontally
    total_width = (total_stars * star_size) + ((total_stars - 1) * gap)
    current_x = (card_width - total_width) / 2
    # Positioned just above the name box (which starts at y=250)
    y_pos = 235 

    def draw_star_shape(x, y, color):
        # A simple 5-point star polygon
        points = [
            (x + 6, y), (x + 8, y + 4), (x + 12, y + 4), 
            (x + 9, y + 7), (x + 10, y + 11), (x + 6, y + 9), 
            (x + 2, y + 11), (x + 3, y + 7), (x, y + 4), (x + 4, y + 4)
        ]
        draw.polygon(points, fill=color, outline="black")

    # Draw Red Stars first (representing the second lap)
    for _ in range(red_count):
        draw_star_shape(current_x, y_pos, STAR_RED)
        current_x += star_size + gap
    
    # Draw Yellow Stars
    for _ in range(yellow_count):
        draw_star_shape(current_x, y_pos, STAR_YELLOW)
        current_x += star_size + gap


def create_character_card(char_data, card_size=(200, 300)):
    card = Image.new("RGBA", card_size, (20, 20, 20, 255))
    draw = ImageDraw.Draw(card)
    rarity = char_data['rarity']
    theme = THEMES.get(rarity, THEMES["R"])

    # Image
    img = char_data.get('image_obj')
    if img:
        img = ImageOps.fit(img, (card_size[0], card_size[1] - 50),
                           method=Image.Resampling.LANCZOS)
        img = apply_holo_effect(img, char_data['rarity'])
        card.paste(img, (0, 0))

    # --- DUPE STARS ---
    # Drawn after pasting the image to ensure they sit on top and aren't affected by holo sheen
    dupe_level = char_data.get('dupe_level', 0)
    draw_dupe_stars(draw, dupe_level, card_size[0])

    # Text Box
    draw.rectangle([0, 250, 200, 300], fill="#151515")
    
    if rarity == "SSR":
        for x in range(200):
            hue = int((x / 200) * 255)
            if hue < 85: color = (255, hue * 3, 0)
            elif hue < 170: color = (255 - (hue - 85) * 3, 255, 0)
            else: color = (0, 255, (hue - 170) * 3)
            draw.line([(x, 250), (x, 254)], fill=color)
    else:
        draw.rectangle([0, 250, 200, 254], fill=theme["hex"])

    # Name Scaling
    name = char_data['name']
    font_name = get_fitted_font(draw, name, 190, FONT_PATH, max_font_size=36)

    bbox = draw.textbbox((0, 0), name, font=font_name)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x_pos = (200 - text_width) / 2
    y_pos = 250 + (50 - text_height) / 2 - 4
    draw.text((x_pos, y_pos), name, font=font_name, fill="white")

    # Rarity Tag
    try:
        font_bold = ImageFont.truetype(str(FONT_PATH), 24)
    except:
        font_bold = ImageFont.load_default()

    rarity_text = char_data['rarity']
    text_x, text_y = 8, 5
    draw.text((text_x + 2, text_y + 2), rarity_text, font=font_bold, fill="black")
    draw.text((text_x, text_y), rarity_text, font=font_bold, fill=theme["hex"])
    draw.text((text_x, text_y), rarity_text, font=font_bold, fill=theme["hex"], stroke_width=1, stroke_fill="white")

    # Border
    border_width = 5 if rarity != "R" else 2
    if rarity == "SSR":
        for i in range(200):
            hue = int((i / 200) * 255)
            if hue < 85: color = (255, hue * 3, 0)
            elif hue < 170: color = (255 - (hue - 85) * 3, 255, 0)
            else: color = (0, 255, (hue - 170) * 3)
            draw.line([(i, 0), (i, border_width)], fill=color)
            draw.line([(i, 299), (i, 299 - border_width)], fill=color)
        
        for j in range(300):
            hue = int((j / 300) * 255)
            if hue < 85: color = (255, hue * 3, 0)
            elif hue < 170: color = (255 - (hue - 85) * 3, 255, 0)
            else: color = (0, 255, (hue - 170) * 3)
            draw.line([(0, j), (border_width, j)], fill=color)
            draw.line([(199, j), (199 - border_width, j)], fill=color)
    else:
        border_color = theme["hex"] if rarity != "R" else "#333333"
        draw.rectangle([0, 0, 199, 299], outline=border_color, width=border_width)

    return card


async def generate_10_pull_image(character_list):
    canvas_w, canvas_h = 1100, 700
    try:
        base_img = Image.open(str(BG_PATH)).convert("RGBA").resize((canvas_w, canvas_h))
    except:
        base_img = Image.new("RGBA", (canvas_w, canvas_h), "#121212")

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_image(session, char['image_url']) for char in character_list]
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
    canvas_w, canvas_h = 1200, 550
    base_img = Image.new("RGBA", (canvas_w, canvas_h), (10, 10, 10, 255))
    draw = ImageDraw.Draw(base_img)

    try:
        font_large = ImageFont.truetype(str(FONT_PATH), 45)
        font_medium = ImageFont.truetype(str(FONT_PATH), 26)
        font_small = ImageFont.truetype(str(FONT_PATH), 18)
    except:
        font_large = font_medium = font_small = ImageFont.load_default()

    total_power = sum(char['power'] for char in team_list if char)
    header_text = f"SQUAD TOTAL POWER: {total_power:,}"
    bbox = draw.textbbox((0, 0), header_text, font=font_large)
    tx_w = bbox[2] - bbox[0]
    draw.text(((canvas_w - tx_w) / 2, 25), header_text, font=font_large, fill="#FFD700")

    async with aiohttp.ClientSession() as session:
        tasks = []
        indices = []
        for i, char in enumerate(team_list):
            if char:
                tasks.append(fetch_image(session, char['image_url']))
                indices.append(i)
        
        if tasks:
            downloaded = await asyncio.gather(*tasks)
            for i, img in zip(indices, downloaded):
                team_list[i]['image_obj'] = img

    start_x, start_y, gap_x = 70, 100, 15

    for i, char in enumerate(team_list):
        x, y = start_x + (i * (200 + gap_x)), start_y

        if char:
            card = create_character_card(char)
            base_img.paste(card, (x, y), card)
            
            p_text = f"⚔️ {char['power']:,}"
            p_bbox = draw.textbbox((0, 0), p_text, font=font_medium)
            px_w = p_bbox[2] - p_bbox[0]
            draw.text((x + (200 - px_w) / 2, y + 310), p_text, font=font_medium, fill="white")
            
            import json
            skills = char.get('ability_tags', [])
            if isinstance(skills, str):
                try:
                    skills = json.loads(skills)
                except:
                    skills = [skills] if skills.strip() else []
            
            active_skills = [str(s).capitalize() for s in skills if s and str(s).strip()]
            s_text = "\n".join(active_skills) if active_skills else "No Skills"
            s_color = "#AAAAAA" if not active_skills else "#00FF7F"
            s_bbox = draw.textbbox((0, 0), s_text, font=font_small)
            sx_w = s_bbox[2] - s_bbox[0]
            draw.text((x + (200 - sx_w) / 2, y + 345), s_text, font=font_small, fill=s_color)
            
        else:
            empty_slot = Image.new("RGBA", (200, 300), (30, 30, 30, 255))
            e_draw = ImageDraw.Draw(empty_slot)
            e_draw.rectangle([0, 0, 199, 299], outline="#444444", width=2)
            text = f"SLOT {i + 1}"
            bbox = e_draw.textbbox((0, 0), text, font=font_medium)
            tx_w, tx_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            e_draw.text(((200 - tx_w) / 2, (300 - tx_h) / 2), text, font=font_medium, fill="#666666")
            base_img.paste(empty_slot, (x, y), empty_slot)

    output = io.BytesIO()
    base_img.save(output, format="PNG")
    output.seek(0)
    return output


async def generate_banner_image(character_data_list, banner_name, end_timestamp):
    banner_w, banner_h = 800, 450
    canvas = Image.new('RGB', (banner_w, banner_h), (20, 20, 20))
    strip_w = banner_w // len(character_data_list)

    async with aiohttp.ClientSession() as session:
        for i, char in enumerate(character_data_list):
            async with session.get(char['image_url']) as resp:
                if resp.status == 200:
                    img_data = await resp.read()
                    char_img = Image.open(io.BytesIO(img_data)).convert("RGBA")
                    
                    aspect = char_img.width / char_img.height
                    target_h = banner_h
                    target_w = int(target_h * aspect)
                    char_img = char_img.resize((target_w, target_h), Image.LANCZOS)
                    
                    left = (char_img.width - strip_w) // 2
                    char_img = char_img.crop((left, 0, left + strip_w, banner_h))
                    canvas.paste(char_img, (i * strip_w, 0), char_img)

    draw = ImageDraw.Draw(canvas)
    font_bold = ImageFont.truetype("assets/fonts/bold_font.ttf", 45)
    font_small = ImageFont.truetype("assets/fonts/bold_font.ttf", 25)
    
    overlay_h = 100
    draw.rectangle([0, banner_h - overlay_h, banner_w, banner_h], fill=(0, 0, 0, 180))
    draw.text((20, banner_h - 90), f"RATE UP: {banner_name.upper()}", font=font_bold, fill=(255, 215, 0))
    
    expiry_str = datetime.fromtimestamp(end_timestamp).strftime("%b %d, %Y - %H:%M")
    draw.text((22, banner_h - 35), f"ENDS: {expiry_str} UTC", font=font_small, fill=(200, 200, 200))

    out = io.BytesIO()
    canvas.save(out, format="PNG")
    out.seek(0)
    return out


async def generate_battle_image(team1, team2, name1, name2, winner_idx=None):
    W, H = 1200, 850
    canvas = Image.new("RGBA", (W, H), (15, 15, 15, 255))
    draw = ImageDraw.Draw(canvas)
    
    async with aiohttp.ClientSession() as session:
        async def prep_team_cards(team_list, is_right_side=False):
            tasks = []
            for char in team_list:
                if char.get('image_url'):
                    tasks.append(fetch_image(session, char['image_url']))
                else:
                    tasks.append(asyncio.sleep(0, result=None))
            
            images = await asyncio.gather(*tasks)
            cards = []
            for i, img in enumerate(images):
                team_list[i]['image_obj'] = img
                card = create_character_card(team_list[i])
                if is_right_side:
                    card = ImageOps.mirror(card)
                cards.append(card)
            return cards

        cards1, cards2 = await asyncio.gather(
            prep_team_cards(team1, is_right_side=False),
            prep_team_cards(team2, is_right_side=True)
        )

    card_w, card_h, gap = 200, 300, 20
    start_x = (W - (5 * card_w + 4 * gap)) // 2
    
    for i, card in enumerate(cards1):
        x, y = start_x + (i * (card_w + gap)), 100
        if winner_idx == 2: card = ImageOps.grayscale(card)
        canvas.paste(card, (x, y), card)

    for i, card in enumerate(cards2):
        x, y = start_x + (i * (card_w + gap)), 500
        if winner_idx == 1: card = ImageOps.grayscale(card)
        canvas.paste(card, (x, y), card)

    try:
        font_vs = ImageFont.truetype(str(FONT_PATH), 120)
        font_name = ImageFont.truetype(str(FONT_PATH), 45)
    except:
        font_vs = font_name = ImageFont.load_default()

    vs_text = "V S"
    v_bbox = draw.textbbox((0, 0), vs_text, font=font_vs)
    v_w = v_bbox[2] - v_bbox[0]
    draw.text(((W - v_w) // 2, 400), vs_text, font=font_vs, fill="#FF4500", stroke_width=2, stroke_fill="white")
    draw.text((start_x, 40), f"PLAYER: {name1.upper()}", font=font_name, fill="cyan")
    
    bbox2 = draw.textbbox((0, 0), f"OPPONENT: {name2.upper()}", font=font_name)
    n2_w = bbox2[2] - bbox2[0]
    draw.text((W - start_x - n2_w, 440), f"OPPONENT: {name2.upper()}", font=font_name, fill="orange")

    out = io.BytesIO()
    canvas.save(out, format="PNG")
    out.seek(0)
    return out