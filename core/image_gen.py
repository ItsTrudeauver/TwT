from PIL import Image, ImageDraw, ImageFont, ImageOps
import aiohttp
import io
import os

# --- CONFIGURATION ---
# You need a font file in assets/fonts/
# You need a background image in assets/templates/
FONT_PATH = os.path.join("assets", "fonts", "bold_font.ttf") 
BG_PATH = os.path.join("assets", "templates", "gacha_bg.png")

# Rarity Colors (Hex Codes)
COLORS = {
    "SSR": "#FFD700",  # Gold
    "SR": "#A020F0",   # Purple
    "R": "#1E90FF"     # Blue
}

async def fetch_image(url):
    """Downloads an image from a URL into memory."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.read()
                return Image.open(io.BytesIO(data)).convert("RGBA")
    return None

def create_character_card(char_data, card_size=(200, 300)):
    """
    Draws a single character card.
    char_data dict needs: 'image_obj', 'name', 'rarity', 'rank'
    """
    # 1. Base Card
    card = Image.new("RGBA", card_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    
    # 2. Handle Image
    img = char_data['image_obj']
    img = ImageOps.fit(img, (card_size[0], card_size[1] - 50), method=Image.Resampling.LANCZOS)
    card.paste(img, (0, 0))
    
    # 3. Draw Bottom Info Box
    # Color based on Rarity
    border_color = COLORS.get(char_data['rarity'], "#FFFFFF")
    
    draw.rectangle([0, 250, 200, 300], fill="#202020") # Text BG
    draw.rectangle([0, 250, 200, 255], fill=border_color) # Top Stripe
    
    # 4. Text
    try:
        font_name = ImageFont.truetype(FONT_PATH, 16)
        font_small = ImageFont.truetype(FONT_PATH, 12)
    except:
        font_name = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Name (Truncated if too long)
    name = char_data['name']
    if len(name) > 18: name = name[:16] + "..."
    
    # Centering Text roughly
    draw.text((10, 260), name, font=font_name, fill="white")
    draw.text((10, 280), f"#{char_data['rank']} | {char_data['rarity']}", font=font_small, fill=border_color)
    
    # 5. Add Border
    draw.rectangle([0, 0, 199, 299], outline=border_color, width=3)
    
    return card

async def generate_10_pull_image(character_list):
    """
    Stitches 10 character cards into a 5x2 Grid.
    """
    # 1. Setup Canvas
    # Grid: 5 cols x 2 rows. Card size 200x300.
    # Canvas Size: 1100 x 700 (allowing for padding)
    canvas_w, canvas_h = 1100, 700
    
    try:
        base_img = Image.open(BG_PATH).convert("RGBA").resize((canvas_w, canvas_h))
    except FileNotFoundError:
        # Fallback if user forgets the BG file
        base_img = Image.new("RGBA", (canvas_w, canvas_h), "#1a1a1a")

    # 2. Fetch all images concurrently (Speed!)
    for char in character_list:
        char['image_obj'] = await fetch_image(char['image_url'])
        # Fallback for broken links
        if not char['image_obj']:
            char['image_obj'] = Image.new("RGBA", (200, 250), "gray")

    # 3. Paste Loop
    # Starting coordinates (Padding: 50px left, 50px top)
    start_x, start_y = 40, 40
    gap_x, gap_y = 10, 20 # Spacing between cards
    
    for i, char in enumerate(character_list):
        card = create_character_card(char)
        
        # Calculate Position
        row = i // 5  # 0 or 1
        col = i % 5   # 0 to 4
        
        x = start_x + (col * (200 + gap_x))
        y = start_y + (row * (300 + gap_y))
        
        base_img.paste(card, (x, y), card)

    # 4. Save to Bytes
    output = io.BytesIO()
    base_img.save(output, format="PNG")
    output.seek(0)
    return output