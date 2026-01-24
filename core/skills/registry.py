# core/skills/registry.py

from .implementations import (
    SimpleBuffSkill, Lucky7Skill, JokerSkill, AmberSunSkill, EternitySkill,
    OnyxMoonSkill, KamikazeSkill, GuardSkill, EphemeralitySkill,
    ZodiacSkill, ReviveSkill
)

# If a class isn't specified, it defaults to SimpleBuffSkill (or just ignores if logic not needed)
SKILL_DATA = {
    "The Onyx Moon": {
        "description": "Casts Umbra: disable one random enemy skill. If Coco is present, casts Eclipse instead: The unit with the disabled skill also loses 20% power.",
        "value": [129840, 0.20],
        "applies_in": "b",
        "stackable": False,
        "overlap": False,
        "class": OnyxMoonSkill
    },
    "The Amber Sun": {
        "description": "If Agott is present, both units gain 15% power.",
        "value": [129842, 0.15],
        "applies_in": "b",
        "stackable": False,
        "overlap": False,
        "class": AmberSunSkill
    },
    "Eternity": {
        "description": "If Himmel is present, this unit gains 18% power.",
        "value": [184311, 0.18],
        "applies_in": "b",
        "stackable": False,
        "overlap": False,
        "class": EternitySkill
    },
    "Ephemerality": {
        "description": "If Frieren is present, this team gains 3.5% power.",
        "value": [176754, 0.035],
        "applies_in": "b",
        "stackable": False,
        "overlap": False,
        "class": EphemeralitySkill
    },
    "Queen of the Zodiacs": {
        "description": "Trigger 1 random effect at the start of the battle: Rat, Ox, Tiger, Rabbit, Dragon, Snake, Horse, Sheep, Monkey, Rooster, Dog, Pig. \nRat: Increase self-power by 20%.\n Ox: Decrease one opponent character's power by 15%. \n Tiger: Increase team power by 5%. \n Rabbit: Decrease opponent team power by 7%. \n Dragon: This character defaults to highest possible variance point (1.1). \n Snake: When losing battle, draw instead. \n Horse: Decrease this character's power by 10%. Increase a random teammate's power by 20%. \n Sheep: Turn opponent's highest power character's power to this unit's power for this battle. \n Monkey: Swap this character's power with a random opponent's character for this battle. \n Rooster: Increase all allies' power by 3% and this character's power by 6%. \n Dog: Copy your strongest character's power to this character for this battle. \n Pig: Disable one random skill from opponent team for this battle.",
        "value": [0.2, 0.15, 0.05, 0.07, 1.2, 0, [0.1, 0.2], [0.03, 0.06]],
        "applies_in": "b",
        "stackable": False,
        "overlap": False,
        "class": ZodiacSkill
    },
    "Lucky 7": {
        "description": "7% chance of +777% power; 77% chance of +7,777 flat power.",
        "value": 7.77,
        "applies_in": "b",
        "stackable": False,
        "overlap": False,
        "class": Lucky7Skill
    },
    "Surge": {
        "description": "Bonus 25% to character power.",
        "value": 0.25,
        "applies_in": "b",
        "stackable": False,
        "overlap": False,
        "class": SimpleBuffSkill
    },
    "Master of Coin": {
        "description": "Bonus 10% to expedition yield even if not on the team.",
        "value": 0.1,
        "applies_in": "g",
        "stackable": True,
        "overlap": True
        # No battle class needed
    },
    "Hardworker": {
        "description": "Bonus 15% to expedition yield when on the team.",
        "value": 0.15,
        "applies_in": "e",
        "stackable": True,
        "overlap": True
        # No battle class needed
    },
    "Golden Egg": {
        "description": "1% chance to triple this character's power for this battle.",
        "value": 3.0,
        "applies_in": "b",
        "stackable": False,
        "overlap": False,
        "class": SimpleBuffSkill
    },
    "Guard": {
        "description": "Deduct 10% total power from opponent team.",
        "value": 0.10,
        "applies_in": "b",
        "stackable": False,
        "overlap": False,
        "class": GuardSkill
    },
    "Anchor": {
        "description": "Unlocks hidden potential.",
        "value": 0.4, 
        "applies_in": "b",
        "stackable": False,
        "overlap": True,
        "class": SimpleBuffSkill # Treating as simple buff based on 'b' context
    },
    "Revive": {
        "description": "25% chance to turn a lost battle into a DRAW.",
        "value": 0.25,
        "applies_in": "b",
        "stackable": False,
        "overlap": False,
        "class": ReviveSkill
    },
    "Kamikaze": {
        "description": "At start of battle, sacrifice this unit to take out 1 random enemy.",
        "value": 1,
        "applies_in": "b",
        "stackable": False,
        "overlap": False,
        "class": KamikazeSkill
    },
    "Berserk": {
        "description": "25% chance to increase power by 50%.",
        "value": 0.5,
        "applies_in": "b",
        "stackable": False,
        "overlap": False,
        "class": SimpleBuffSkill
    },
    "Royalty": {
        "description": "Victories with this character in the team boosts rewards by 50%.",
        "value": 0.5,
        "applies_in": "b",
        "stackable": False,
        "overlap": False
        # Logic is handled in reward distribution, not power calc
    },
    "The Joker": {
        "description": "In battle, increase or decrease this character's power by 80%.",
        "value": 0.8,
        "applies_in": "b",
        "stackable": False,
        "overlap": True,
        "class": JokerSkill
    },
    "The Long Road": {
        "description": "In expedition, the longer you don't collect rewards, the more you yield (max 24h).",
        "value": 0.24,
        "applies_in": "e",
        "stackable": False,
        "overlap": False
        # No battle class needed
    }
}

def get_skill_info(skill_name):
    """Returns skill metadata with a case-insensitive lookup."""
    target = skill_name.strip().lower()
    for key in SKILL_DATA:
        if key.lower() == target:
            return SKILL_DATA[key]
    return None

def list_all_skills():
    return list(SKILL_DATA.keys())

def create_skill_instance(skill_name, owner_data, owner_idx, side):
    """Factory to instantiate a skill."""
    data = get_skill_info(skill_name)
    if not data: return None
    
    # Check context 'b' or 'g' (global)
    if data['applies_in'] not in ['b', 'g']:
        return None

    klass = data.get("class")
    if not klass:
        # If it's a battle skill but no class defined, ignore or default
        return None
    
    return klass(skill_name, owner_data, owner_idx, side, data.get("value"))