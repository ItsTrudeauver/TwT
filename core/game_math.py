import math
import random

def squash_with_caps(value, soft_cap, hard_cap):
    """
    Applies an aggressive logarithmic squash after a soft cap towards a hard cap.
    """
    if value <= soft_cap:
        return value
    
    excess = value - soft_cap
    # Tuning factor: controls how 'fast' we approach the hard cap wall.
    # Higher = slower approach.
    factor = (hard_cap - soft_cap) * 1.2
    
    # Asymptotic approach: SoftCap + (Margin * (1 - 1/(1 + excess/factor)))
    margin = hard_cap - soft_cap
    squashed = soft_cap + margin * (1 - (1 / (1 + (excess / factor))))
    
    return int(min(squashed, hard_cap))

def calculate_effective_power(raw_favs, rarity="R", rank=10000):
    """
    Requested Logic:
    - SSR (1-250): Base 10,000. Top 1 ~13k, Top 250 ~10.2k. (Logarithmic)
    - SR (251-1500): Base 7,000. Soft 9,000, Hard 9,900.
    - R (1501-10000): Base 4,000. Soft 5,000, Hard 6,250.
    """
    favs = max(1, raw_favs)
    
    if rarity == "SSR":
        # log10(Rank 1 favs ~550k) is ~5.74. log10(Rank 250 favs ~15k) is ~4.17.
        # Shift and scale log value to hit the ~13k and ~10.2k targets.
        log_boost = math.log10(favs)
        # (5.74 - 4.17) * 1780 + 10200 ≈ 12994
        power = 10200 + (log_boost - 4.17) * 1780
        return int(max(10000, power))
        
    elif rarity == "SR":
        # Base 7,000 + contribution. Apply Soft Cap 9,000, Hard Cap 9,900.
        # SR fav counts range roughly 1k to 14k.
        raw_power = 7000 + (favs / 6)
        return squash_with_caps(raw_power, 9000, 9900)
        
    else: # Rarity "R"
        # Base 4,000 + contribution. Apply Soft Cap 5,000, Hard Cap 6,250.
        # R characters have lower fav counts.
        raw_power = 4000 + (favs / 2)
        return squash_with_caps(raw_power, 5000, 6250)

def calculate_team_power(team_list):
    """
    Calculates total power including a 5% boost per duplicate 
    owned by the player for each character in the squad.
    """
    total_power = 0
    for char in team_list:
        if not char: continue
        
        # Use the base 'True Power' from the cache
        base = char.get('true_power', 0)
        
        # Calculate dupe boost: 1.0 for first copy, +0.05 for each extra copy
        dupe_count = char.get('dupe_count', 1)
        boost = 1 + (max(0, dupe_count - 1) * 0.05)
        
        total_power += int(base * boost)
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
    test_cases = [
        ("Rank 1 SSR", "SSR", 550000, 1), 
        ("Rank 250 SSR", "SSR", 15000, 250), 
        ("High SR", "SR", 18000, 300), 
        ("Low R", "R", 500, 5000)
    ]
    for name, rar, favs, rnk in test_cases:
        print(f"{name} ({rar}): {calculate_effective_power(favs, rar, rnk):,}")