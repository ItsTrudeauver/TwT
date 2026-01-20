import math
import random

# --- CONFIGURATION (AGGRESSIVE SQUASHING) ---
SOFT_CAP = 10000  # The "Gatekeeper" Level
LOG_MULTIPLIER = 800  # The "Wall" Height.
# Lower = Harder Wall. (800 is very strict).


def calculate_effective_power(raw_favs, squash_resistance=0.0):
    """
    Converts raw AniList favorites into Battle Power using a Hard Log10 Wall.
    
    The Philosophy:
    - 0 to 10k: Linear Growth (1 fav = 1 power).
    - 10k+: Massive Diminishing Returns.
    
    Result:
    - 10k Char = 10,000 Power
    - 34k Char = ~13,500 Power (Only 35% stronger, despite 3x the likes)
    """
    # 1. Base Case: Below the Cap, power is 1:1
    if raw_favs <= SOFT_CAP:
        return raw_favs

    # 2. The Squashing Logic (Log10)
    # We strip the first 10k, then log the rest.
    excess_favs = raw_favs - SOFT_CAP

    # log10(10,000) = 4.0
    # log10(24,000) = 4.38
    log_boost = math.log10(excess_favs + 1)

    # 3. Apply Resistance
    # A resistance of 0.2 (20%) makes the wall 20% taller.
    adjusted_multiplier = LOG_MULTIPLIER * (1 + squash_resistance)

    effective_power = SOFT_CAP + (log_boost * adjusted_multiplier)

    return int(effective_power)


def calculate_team_power(team_list):
    total_power = 0
    for char in team_list:
        raw = char.get('base_power', 0)
        res = char.get('squash_resistance', 0.0)
        total_power += calculate_effective_power(raw, res)
    return total_power


def simulate_standoff(power_a, power_b):
    """
    Simulates a standoff between two players based on their power levels.
    Returns the theoretical winner and their win chance.
    """
    total = power_a + power_b
    if total == 0:
        return "Draw", 50.0

    chance_a = (power_a / total) * 100
    chance_b = (power_b / total) * 100

    roll = random.uniform(0, 100)

    if roll < chance_a:
        return "Player A", chance_a
    else:
        return "Player B", chance_b


# --- DEBUG BLOCK (Run this to see the "Wall") ---
if __name__ == "__main__":
    test_cases = [("Niche", 2000), ("Gatekeeper", 10000),
                  ("Rising Star", 15000), ("Satoru Gojo", 34000),
                  ("Global #1", 100000)]

    print(f"{'NAME':<12} | {'RAW':<7} | {'EFFECTIVE':<10} | {'ADVANTAGE'}")
    print("-" * 55)

    base_power = calculate_effective_power(10000)

    for name, raw in test_cases:
        eff = calculate_effective_power(raw)
        # Calculate how much stronger they are vs the Gatekeeper
        advantage = f"+{int(((eff/base_power) - 1) * 100)}%"
        print(f"{name:<12} | {raw:<7} | {eff:<10} | {advantage}")
