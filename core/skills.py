# core/skills.py

# core/skills.py

# core/skills.py

SKILL_DATA = {
    "Queen of the Zodiacs": {
        "description": "Trigger 1 random effect at the start of the battle: Rat, Ox, Tiger, Rabbit, Dragon, Snake, Horse, Sheep, Monkey, Rooster, Dog, Pig. \nRat: Increase self-power by 10%.\n Ox: Decrease one opponent character's power by 15%. \n Tiger: Increase team power by 5%. \n Rabbit: Decrease opponent team power by 7%. \n Dragon: This character defaults to highest possible variance point (1.1). \n Snake: When losing battle, draw instead. \n Horse: Decrease this character's power by 10%. Increase a random teammate's power by 20%. \n Sheep: Turn opponent's highest power character's power to this unit's power for this battle. \n Monkey: Swap this character's power with a random opponent's character for this battle. \n Rooster: Increase all allies' power by 3% and this character's power by 6%. \n Dog: Copy your strongest character's power to this character for this battle. \n Pig: Disable one random skill from opponent team for this battle.",
        "value": [0.1, 0.15, 0.05, 0.07, 1.1, 0, [0.1, 0.2], [0.03, 0.06]], # Representing the 777% multiplier
        "applies_in": "b",
        "stackable": False,
        "overlap": False
    },
    
    "Lucky 7": {
        "description": "7% chance of +777% power; 77% chance of +7,777 flat power.",
        "value": 7.77, # Representing the 777% multiplier
        "applies_in": "b",
        "stackable": False,
        "overlap": False
    },
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