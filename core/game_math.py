import math
import random

def calculate_effective_power(raw_favs, rarity="R", squash_resistance=0.0):
    """
    Tiered Power Logic where Rarity determines floors and ceilings.
    SSR: 10,000+ (Log squashed gap)
    SR:  7,000 - 8,999
    R:   3,000 - 5,999
    """
    favs = max(1, raw_favs)
    
    if rarity == "SSR":
        # Base 10,000. Log squash ensures a narrow gap between SSRs.
        log_boost = math.log10(favs)
        adjusted_mult = 500 * (1 + squash_resistance)
        power = 10000 + (log_boost * adjusted_mult)
        
    elif rarity == "SR":
        # Corridor: 7,000 to 8,999.
        log_boost = math.log10(favs)
        power = 7000 + (log_boost * 380)
        power = min(power, 8999)
        
    else: # Rarity "R"
        # Corridor: 3,000 to 5,999.
        log_boost = math.log10(favs)
        power = 3000 + (log_boost * 580)
        power = min(power, 5999)

    return int(power)

def calculate_team_power(team_list):
    total_power = 0
    for char in team_list:
        if not char: continue
        raw = char.get('base_power', 0)
        rarity = char.get('rarity', 'R')
        res = char.get('squash_resistance', 0.0)
        total_power += calculate_effective_power(raw, rarity, res)
    return total_power

def simulate_standoff(power_a, power_b):
    total = power_a + power_b
    if total == 0: return "Draw", 50.0
    chance_a = (power_a / total) * 100
    roll = random.uniform(0, 100)
    if roll < chance_a:
        return "Player A", chance_a
    else:
        return "Player B", (100 - (power_a / total) * 100)

if __name__ == "__main__":
    test_cases = [("R Char", "R", 100), ("SR Char", "SR", 5000), ("SSR Char", "SSR", 10000), ("Gojo", "SSR", 34000)]
    for name, rar, raw in test_cases:
        print(f"{name}: {calculate_effective_power(raw, rar):,}")