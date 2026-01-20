# core/skills.py

# core/skills.py

# core/skills.py

SKILL_DATA = {
    "Surge": {
        "description": "Bonus 25% to character power.",
        "value": 0.25,
        "applies_in": "b",
        "stackable": False,
        "overlap": False
    },
    "Master of Coin": {
        "description": "Bonus 10% to expedition yield even if not on the team.",
        "value": 0.1,
        "applies_in": "g",
        "stackable": True,
        "overlap": True
    },
    "Hardworker": {
        "description": "Bonus 15% to expedition yield when on the team.",
        "value": 0.15,
        "applies_in": "e",
        "stackable": True,
        "overlap": True
    },
    "Golden Egg": {
        "description": "1% chance to triple this character's power for this battle.",
        "value": 3.0,
        "applies_in": "b",
        "stackable": False,
        "overlap": False
    },
    "Guard": {
        "description": "Deduct 10% total power from opponent team.",
        "value": 0.10,
        "applies_in": "b",
        "stackable": False,
        "overlap": False
    },
    "Anchor": {
        "description": "Unlocks hidden potential.",
        "value": 0.4, 
        "applies_in": "b",
        "stackable": False,
        "overlap": True
    },
    "Revive": {
        "description": "25% chance to turn a lost battle into a DRAW.",
        "value": 0.25,
        "applies_in": "b",
        "stackable": False,
        "overlap": False
    },
    "Kamikaze": {
        "description": "At start of battle, sacrifice this unit to take out 1 random enemy.",
        "value": 1,
        "applies_in": "b",
        "stackable": False,
        "overlap": False
    },
    "Berserk": {
        "description": "25% chance to increase power by 50%.",
        "value": 0.5,
        "applies_in": "b",
        "stackable": False,
        "overlap": False
    },
    "Royalty": {
        "description": "Victories with this character in the team boosts rewards by 50%.",
        "value": 0.5,
        "applies_in": "b",
        "stackable": False,
        "overlap": False
    },
    "The Joker": {
        "description": "In battle, increase or decrease this character's power by 40%.",
        "value": 0.4,
        "applies_in": "b",
        "stackable": False,
        "overlap": True
    },
    "The Long Road": {
        "description": "In expedition, the longer you don't collect rewards, the more you yield (max 24h).",
        "value": 0.24,
        "applies_in": "e",
        "stackable": False,
        "overlap": False
    }
}
def get_skill_info(skill_name):
    """Returns skill metadata if it exists."""
    return SKILL_DATA.get(skill_name.title())

def list_all_skills():
    """Returns a list of all valid skill names."""
    return list(SKILL_DATA.keys())