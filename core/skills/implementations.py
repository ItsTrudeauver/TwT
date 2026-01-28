# core/skills/implementations.py

import random
import json
from .engine import BattleSkill, BattleContext

# --- BUFFS ---

class SimpleBuffSkill(BattleSkill):
    """Handles standard percentage buffs like Surge and Berserk."""
    async def get_power_modifier(self, ctx: BattleContext, current_power):
        if ctx.is_suppressed(self.side, self.name): return 1.0
        
        if self.name == "Surge":
            ctx.add_log(self.side, self.idx, f"⚡ **{self.owner['name']}** activated **Surge** (+{int(self.val*100)}%)!")
            return 1.0 + self.val
            
        if self.name == "Berserk":
            if random.random() < 0.25:
                ctx.add_log(self.side, self.idx, f"💢 **{self.owner['name']}** went **Berserk** (+{int(self.val*100)}%)!")
                return 1.0 + self.val

        if self.name == "Golden Egg":
             if random.random() < 0.01:
                ctx.add_log(self.side, self.idx, f"🥚 **{self.owner['name']}** hatched a **Golden Egg** ({self.val}x Power)!")
                return self.val
        
        return 1.0

class Lucky7Skill(BattleSkill):
    async def get_power_modifier(self, ctx: BattleContext, current_power):
        if ctx.is_suppressed(self.side, self.name): return 1.0
        
        if random.random() < 0.07:
            ctx.add_log(self.side, self.idx, f"✨ **{self.owner['name']}** hit the Lucky 7 Jackpot (+777% Power)!")
            return 8.77
        elif random.random() < 0.77:
            ctx.add_log(self.side, self.idx, f"🍀 **{self.owner['name']}** gained a Lucky 7 flat bonus (+7,777)!")
            ctx.flat_bonuses[self.side][self.idx] += 7777
        return 1.0

class JokerSkill(BattleSkill):
    async def get_power_modifier(self, ctx: BattleContext, current_power):
        if ctx.is_suppressed(self.side, self.name): return 1.0
        
        if random.random() < 0.5:
            ctx.add_log(self.side, self.idx, f"🃏 **{self.owner['name']}**'s Joker was a BUFF (+{int(self.val*100)}%)!")
            return 1.0 + self.val
        else:
            ctx.add_log(self.side, self.idx, f"🃏 **{self.owner['name']}**'s Joker was a DEBUFF (-{int(self.val*100)}%)!")
            return 1.0 - self.val

class AmberSunSkill(BattleSkill):
    async def get_power_modifier(self, ctx: BattleContext, current_power):
        if ctx.is_suppressed(self.side, self.name): return 1.0
        
        # Value is [129842, 0.15] (Agott ID, percent)
        agott_id = self.val[0]
        bonus = self.val[1]
        
        my_team = ctx.get_team(self.side)
        
        # Logic 1: If Agott is present, this unit gains power
        if any(c.get('anilist_id') == agott_id for c in my_team if c):
            ctx.add_log(self.side, self.idx, f"☀️ **{self.owner['name']}** resonated with Agott (+{int(bonus*100)}%)!")
            return 1.0 + bonus
            
        return 1.0

    async def on_battle_start(self, ctx: BattleContext):
       
        if ctx.is_suppressed(self.side, self.name): return
        
        agott_id = self.val[0]
        bonus = self.val[1]
        my_team = ctx.get_team(self.side)
        
        for i, char in enumerate(my_team):
            if char and char.get('anilist_id') == agott_id:
                # We found Agott. Apply the multiplier to him directly in the context.
                # Avoid double buffing if Agott is the one holding the skill (he gets it via get_power_modifier)
                if i != self.idx:
                    ctx.multipliers[self.side][i] *= (1.0 + bonus)
                    ctx.add_log(self.side, i, f"☀️ **{char['name']}** was empowered by The Amber Sun (+{int(bonus*100)}%)!")

class EternitySkill(BattleSkill):
    async def get_power_modifier(self, ctx: BattleContext, current_power):
        if ctx.is_suppressed(self.side, self.name): return 1.0
        
        himmel_id = self.val[0]
        bonus = self.val[1]
        my_team = ctx.get_team(self.side)
        
        if any(c.get('anilist_id') == himmel_id for c in my_team if c):
            ctx.add_log(self.side, self.idx, f"🌌 **Duo Skill - Eternity**: {self.owner['name']} found strength in memory of Himmel (+{int(bonus*100)}%)!")
            return 1.0 + bonus
        return 1.0

class FelineFealtySkill(BattleSkill):
    async def get_power_modifier(self, ctx: BattleContext, current_power):
        if ctx.is_suppressed(self.side, self.name): return 1.0
        
        # Value is [207, 0.10, 0.025] (Tohru ID, Buff, Debuff)
        tohru_id = self.val[0]
        buff = self.val[1]
        
        my_team = ctx.get_team(self.side)
        
        # Effect 1 (Self): If Tohru is present, this unit gains power
        if any(c.get('anilist_id') == tohru_id for c in my_team if c):
            ctx.add_log(self.side, self.idx, f"🍙 **{self.owner['name']}** is devoted to Tohru (+{int(buff*100)}%)!")
            return 1.0 + buff
            
        return 1.0

    async def on_battle_start(self, ctx: BattleContext):
        if ctx.is_suppressed(self.side, self.name): return
        
        tohru_id = self.val[0]
        buff = self.val[1]
        debuff = self.val[2]
        
        my_team = ctx.get_team(self.side)
        
        # Check if Tohru is present
        has_tohru = any(c.get('anilist_id') == tohru_id for c in my_team if c)
        
        if has_tohru:
            # Effect 1 (Partner): Find Tohru and buff her (if she isn't the skill owner)
            for i, char in enumerate(my_team):
                if char and char.get('anilist_id') == tohru_id:
                    # Avoid double buffing if Tohru is the one holding the skill (she gets it via get_power_modifier)
                    if i != self.idx:
                        ctx.multipliers[self.side][i] *= (1.0 + buff)
                        ctx.add_log(self.side, i, f"🍙 **{char['name']}** felt the bond of Feline Fealty (+{int(buff*100)}%)!")
            
            # Effect 2: Reduce enemy team power
            enemy_team = ctx.get_team(self.enemy_side)
            for i in range(len(enemy_team)):
                ctx.multipliers[self.enemy_side][i] *= (1.0 - debuff)
            ctx.add_log(self.side, self.idx, f"🍙 **Feline Fealty** softened the enemy blows (-{debuff*100}%)!")

class EntwinedSoulsSkill(BattleSkill):
    async def on_battle_start(self, ctx: BattleContext):
        if ctx.is_suppressed(self.side, self.name): return
        
        kyo_id = self.val[0]
        effectiveness = self.val[1] # 1.2 (+20% effectiveness)
        
        my_team = ctx.get_team(self.side)
        
        # Condition: Kyo Sohma must be present
        if not any(c.get('anilist_id') == kyo_id for c in my_team if c):
            return

        # Restricted Effect Pool
        pool = ["Ox", "Tiger", "Rabbit", "Rooster", "Pig", "Horse"]
        chosen = random.choice(pool)
        
        prefix = f"📿 **{self.owner['name']}**'s Soul Entwined with Kyo ({chosen}): "
        
        # Base values derived from Queen of the Zodiacs, scaled by effectiveness (1.2)
        
        if chosen == "Ox":
            # Base 0.2 -> Scaled 0.24
            val = 0.2 * effectiveness
            enemy_team = ctx.get_team(self.enemy_side)
            valid = [i for i, c in enumerate(enemy_team) if c]
            if valid:
                t = random.choice(valid)
                ctx.multipliers[self.enemy_side][t] *= (1 - val)
                ctx.add_log(self.side, self.idx, prefix + f"Crushed **{enemy_team[t]['name']}** (-{int(val*100)}% Power)!")
            else:
                ctx.add_log(self.side, self.idx, prefix + "No enemies to crush.")

        elif chosen == "Tiger":
            # Base 0.05 -> Scaled 0.06
            val = 0.05 * effectiveness
            for i in range(len(ctx.get_team(self.side))):
                ctx.multipliers[self.side][i] *= (1 + val)
            ctx.add_log(self.side, self.idx, prefix + f"Tiger Spirit boosted the team (+{int(val*100)}%)!")

        elif chosen == "Rabbit":
            # Base 0.07 -> Scaled 0.084
            val = 0.07 * effectiveness
            for i in range(len(ctx.get_team(self.enemy_side))):
                ctx.multipliers[self.enemy_side][i] *= (1 - val)
            ctx.add_log(self.side, self.idx, prefix + f"Rabbit Spirit weakened the enemy (-{float(val*100):.1f}%)!")

        elif chosen == "Rooster":
            # Base [0.03, 0.06] -> Scaled [0.036, 0.072]
            val_team = 0.03 * effectiveness
            val_self = 0.06 * effectiveness
            for i in range(len(ctx.get_team(self.side))):
                ctx.multipliers[self.side][i] *= (1 + val_team)
            ctx.multipliers[self.side][self.idx] *= (1 + val_self)
            ctx.add_log(self.side, self.idx, prefix + "Rooster Spirit crowed! Self and Team power increased!")

        elif chosen == "Pig":
            # Logic same as base Zodiac, just triggered via this skill
            enemy_team = ctx.get_team(self.enemy_side)
            valid_targets = []
            for i, c in enumerate(enemy_team):
                if not c: continue
                tags = c.get('ability_tags', [])
                if isinstance(tags, str): tags = json.loads(tags)
                for tag in tags:
                    if tag != "Queen of the Zodiacs": valid_targets.append(tag)
            
            if valid_targets:
                target_skill = random.choice(valid_targets)
                ctx.suppress_skill(self.enemy_side, target_skill)
                ctx.add_log(self.side, self.idx, prefix + f"Boar Spirit muddied the waters, disabling **{target_skill}**!")
            else:
                ctx.add_log(self.side, self.idx, prefix + "Boar Spirit appeared, but nothing happened.")

        elif chosen == "Horse":
            # Base [0.1, 0.3] -> Scaled [0.12, 0.36]
            val_self_debuff = 0.1 * effectiveness
            val_ally_buff = 0.3 * effectiveness
            
            ctx.multipliers[self.side][self.idx] *= (1 - val_self_debuff)
            my_team = ctx.get_team(self.side)
            others = [i for i, c in enumerate(my_team) if c and i != self.idx]
            if others:
                t = random.choice(others)
                ctx.multipliers[self.side][t] *= (1 + val_ally_buff)
                ctx.add_log(self.side, self.idx, prefix + f"Horse Spirit sacrificed strength (-{int(val_self_debuff*100)}%) to empower **{my_team[t]['name']}** (+{int(val_ally_buff*100)}%)!")
            else:
                ctx.add_log(self.side, self.idx, prefix + "No allies to empower.")
# --- DEBUFFS / CONTROL ---

class OnyxMoonSkill(BattleSkill):
    async def on_battle_start(self, ctx: BattleContext):
        # Note: Onyx Moon usually ignores suppression because it fires at Start of Battle (same priority as Pig)
        # But if you want it suppressible by a faster Pig, uncomment the check.
        # if ctx.is_suppressed(self.side, self.name): return

        enemy_team = ctx.get_team(self.enemy_side)
        # Find valid targets (enemies with skills, excluding Zodiacs usually)
        valid_targets = []
        for i, char in enumerate(enemy_team):
            if not char: continue
            tags = char.get('ability_tags', [])
            if isinstance(tags, str): tags = json.loads(tags)
            for tag in tags:
                if tag != "Queen of the Zodiacs": 
                    valid_targets.append((i, tag))
        
        if not valid_targets:
            ctx.add_log(self.side, self.idx, f"🌑 **{self.owner['name']}** cast **The Onyx Moon**, but no skills to silence.")
            return

        target_idx, target_skill = random.choice(valid_targets)
        ctx.suppress_skill(self.enemy_side, target_skill)

        # Check for Coco Synergy (ID 129840)
        coco_id = self.val[0]
        my_team = ctx.get_team(self.side)
        has_coco = any(c.get('anilist_id') == coco_id for c in my_team if c)

        if has_coco:
            # Eclipse: Apply Debuff (-25%)
            ctx.multipliers[self.enemy_side][target_idx] *= 0.75
            ctx.add_log(self.side, self.idx, f"🌑 **{self.owner['name']}** cast **Eclipse** (w/ Coco)! Silenced **{target_skill}** & drained target.")
        else:
            ctx.add_log(self.side, self.idx, f"🌑 **{self.owner['name']}** cast **Umbra**! Silenced **{target_skill}**.")

class KamikazeSkill(BattleSkill):
    async def on_battle_start(self, ctx: BattleContext):
        if ctx.is_suppressed(self.side, self.name): return
        
        enemy_team = ctx.get_team(self.enemy_side)
        # Find living enemies (check if power multiplier is not already 0)
        valid_targets = [i for i, c in enumerate(enemy_team) if c and ctx.multipliers[self.enemy_side][i] > 0]
        
        if valid_targets:
            target_idx = random.choice(valid_targets)
            ctx.multipliers[self.enemy_side][target_idx] = 0.0 # Eliminated
            ctx.add_log(self.side, self.idx, f"💥 **Kamikaze** eliminated **{enemy_team[target_idx]['name']}**!")

class GuardSkill(BattleSkill):
    async def on_battle_start(self, ctx: BattleContext):
        if ctx.is_suppressed(self.side, self.name): return

        # Deduct 10% total power from opponent team.
        # We achieve this by applying a 0.9 multiplier to all existing enemies.
        enemy_team = ctx.get_team(self.enemy_side)
        for i in range(len(enemy_team)):
            ctx.multipliers[self.enemy_side][i] *= (1.0 - self.val)
        ctx.add_log(self.side, self.idx, f"🛡️ **Guard** reduced enemy team power by {int(self.val*100)}%!")

class EphemeralitySkill(BattleSkill):
    async def on_battle_start(self, ctx: BattleContext):
        if ctx.is_suppressed(self.side, self.name): return
        
        frieren_id = self.val[0]
        bonus = self.val[1]
        my_team = ctx.get_team(self.side)
        
        if any(c.get('anilist_id') == frieren_id for c in my_team if c):
             for i in range(len(my_team)):
                ctx.multipliers[self.side][i] *= (1.0 + bonus)
             ctx.add_log(self.side, self.idx, f"🌿 **Duo Skill - Ephemerality**: Frieren's presence boosted the party!")

# --- ZODIACS ---

class ZodiacSkill(BattleSkill):
    async def on_battle_start(self, ctx: BattleContext):
        if ctx.is_suppressed(self.side, self.name): return

        zodiacs = ["Rat", "Ox", "Tiger", "Rabbit", "Dragon", "Snake", "Horse", "Sheep", "Monkey", "Rooster", "Dog", "Pig"]
        chosen = random.choice(zodiacs)
        vals = self.val # The list of values from SKILL_DATA
        
        prefix = f"👑 **{self.owner['name']}** invoked the **{chosen}** Zodiac: "
        
        if chosen == "Rat":
            ctx.multipliers[self.side][self.idx] *= (1 + vals[0])
            ctx.add_log(self.side, self.idx, prefix + f"Power surge (+{int(vals[0]*100)}%)!")

        elif chosen == "Ox":
            enemy_team = ctx.get_team(self.enemy_side)
            valid = [i for i, c in enumerate(enemy_team) if c]
            if valid:
                t = random.choice(valid)
                ctx.multipliers[self.enemy_side][t] *= (1 - vals[1])
                ctx.add_log(self.side, self.idx, prefix + f"Crushed **{enemy_team[t]['name']}** (-{int(vals[1]*100)}% Power)!")
            else:
                ctx.add_log(self.side, self.idx, prefix + "But no enemies to crush.")

        elif chosen == "Tiger":
            for i in range(len(ctx.get_team(self.side))):
                ctx.multipliers[self.side][i] *= (1 + vals[2])
            ctx.add_log(self.side, self.idx, prefix + f"Roared, boosting the team (+{int(vals[2]*100)}%)!")

        elif chosen == "Rabbit":
            for i in range(len(ctx.get_team(self.enemy_side))):
                ctx.multipliers[self.enemy_side][i] *= (1 - vals[3])
            ctx.add_log(self.side, self.idx, prefix + f"Beguiled the enemy team (-{int(vals[3]*100)}%)!")

        elif chosen == "Dragon":
            # Defaults to highest possible variance (1.1).
            # We set a flag on this specific slot index
            if "variance_override" not in ctx.flags: ctx.flags["variance_override"] = {}
            ctx.flags["variance_override"][f"{self.side}_{self.idx}"] = vals[4]
            ctx.add_log(self.side, self.idx, prefix + "Seized control of fate (Max Variance Locked)!")

        elif chosen == "Snake":
            ctx.flags["snake_trap"] = True
            ctx.add_log(self.side, self.idx, prefix + "Lidless eyes watch... (Losses will become DRAWS)!")

        elif chosen == "Horse":
            ctx.multipliers[self.side][self.idx] *= (1 - vals[6][0])
            my_team = ctx.get_team(self.side)
            others = [i for i, c in enumerate(my_team) if c and i != self.idx]
            if others:
                t = random.choice(others)
                ctx.multipliers[self.side][t] *= (1 + vals[6][1])
                ctx.add_log(self.side, self.idx, prefix + f"Sacrificed strength to empower **{my_team[t]['name']}**!")
            else:
                ctx.add_log(self.side, self.idx, prefix + "No allies to empower.")

        elif chosen == "Rooster":
            # Increase all allies by 3%, self by 6% (Self total 9% effectively or 6%? Description says "Self 6%")
            # Vals[7] = [0.03, 0.06]
            for i in range(len(ctx.get_team(self.side))):
                ctx.multipliers[self.side][i] *= (1 + vals[7][0])
            ctx.multipliers[self.side][self.idx] *= (1 + vals[7][1])
            ctx.add_log(self.side, self.idx, prefix + "The dawn awakens! Self and Team power increased!")

        elif chosen == "Pig":
            enemy_team = ctx.get_team(self.enemy_side)
            valid_targets = []
            for i, c in enumerate(enemy_team):
                if not c: continue
                tags = c.get('ability_tags', [])
                if isinstance(tags, str): tags = json.loads(tags)
                for tag in tags:
                    if tag != "Queen of the Zodiacs": valid_targets.append(tag)
            
            if valid_targets:
                target_skill = random.choice(valid_targets)
                ctx.suppress_skill(self.enemy_side, target_skill)
                ctx.add_log(self.side, self.idx, prefix + f"Muddied the waters, disabling **{target_skill}**!")
            else:
                ctx.add_log(self.side, self.idx, prefix + "Muddied the waters, but nothing happened.")

        # Logic for Sheep, Monkey, Dog handled in post_calc
        elif chosen in ["Sheep", "Monkey", "Dog"]:
            # We store which effect happened to trigger it in post_calc
            if "zodiac_post_effects" not in ctx.flags: ctx.flags["zodiac_post_effects"] = []
            ctx.flags["zodiac_post_effects"].append({
                "type": chosen,
                "side": self.side,
                "idx": self.idx,
                "vals": vals
            })
            if chosen == "Sheep":
                ctx.add_log(self.side, self.idx, prefix + "Mirrored the aura of the strongest foe!")
            elif chosen == "Monkey":
                ctx.add_log(self.side, self.idx, prefix + "Prepared a prank...")
            elif chosen == "Dog":
                ctx.add_log(self.side, self.idx, prefix + "Loyally copied the power of the strongest ally!")

    async def on_post_power_calculation(self, ctx: BattleContext, final_powers):
        # Handle Sheep, Monkey, Dog
        if "zodiac_post_effects" not in ctx.flags: return
        
        effects = [e for e in ctx.flags["zodiac_post_effects"] if e["side"] == self.side and e["idx"] == self.idx]
        
        for eff in effects:
            zt = eff["type"]
            idx = eff["idx"]
            
            if zt == "Sheep":
                # Turn opp highest power to this unit's power (Wait, description: "Turn opponent's highest power... to THIS unit's power"?)
                # Description: "Turn opponent's highest power character's power to this unit's power" implies nerf?
                # Or "Copy opponent's highest power"?
                # Re-reading logic in old file: `effect["sheep_logic"] = True` -> `temp_powers[idx] = opp_max`.
                # Old logic COPIED the enemy max power TO the sheep user.
                opp_powers = final_powers[self.enemy_side]
                if opp_powers:
                    opp_max = max(opp_powers)
                    final_powers[self.side][idx] = opp_max
            
            elif zt == "Dog":
                # Copy strongest ally
                my_powers = final_powers[self.side]
                if my_powers:
                    final_powers[self.side][idx] = max(my_powers)

            elif zt == "Monkey":
                # Swap with random opponent
                opp_powers = final_powers[self.enemy_side]
                valid_opp_indices = [i for i, p in enumerate(opp_powers) if p > 0]
                if valid_opp_indices:
                    target = random.choice(valid_opp_indices)
                    # Swap
                    my_val = final_powers[self.side][idx]
                    opp_val = final_powers[self.enemy_side][target]
                    final_powers[self.side][idx] = opp_val
                    final_powers[self.enemy_side][target] = my_val
                    
                    enemy_name = ctx.get_team(self.enemy_side)[target]['name']
                    ctx.add_log(self.side, idx, f"👑 **Monkey Zodiac**: Pranked **{enemy_name}**, swapping power levels!")

# --- OUTCOME MODIFIERS ---

class ReviveSkill(BattleSkill):
    async def on_battle_end(self, ctx, result):
        if result == "LOSS":
             if random.random() < self.val:
                 ctx.add_log(self.side, self.idx, f"💖 **Revive** triggered! The defeat was turned into a **DRAW**.")
                 return "DRAW"
        return None