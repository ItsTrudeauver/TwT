import random
import json
from core.skills import SKILL_DATA

class SkillHandler:
    @staticmethod
    def get_active_skills(character_list, context='b'):
        """
        Filters a list of characters to find active skills based on context (b/e/g).
        Returns: { "SkillName": count }
        """
        active_effects = {}
        seen_non_overlap = set()

        for char in character_list:
            if not char: continue
            
            tags = char.get('ability_tags', [])
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except json.JSONDecodeError:
                    tags = []

            for skill_name in tags:
                config = SKILL_DATA.get(skill_name)
                if not config or (config['applies_in'] not in [context, 'g']):
                    continue

                if not config['overlap'] and skill_name in seen_non_overlap:
                    continue
                seen_non_overlap.add(skill_name)

                if config['stackable']:
                    active_effects[skill_name] = active_effects.get(skill_name, 0) + 1
                else:
                    active_effects[skill_name] = 1
        
        return active_effects

    @staticmethod
    def handle_zodiac_roll(char, team_list, opponent_team_list):
        """
        Triggers 1 random Zodiac effect.
        Returns: (effect_dict, log_string)
        """
        zodiacs = ["Rat", "Ox", "Tiger", "Rabbit", "Dragon", "Snake", "Horse", 
                   "Sheep", "Monkey", "Rooster", "Dog", "Pig"]
        chosen = random.choice(zodiacs)
        vals = SKILL_DATA["Queen of the Zodiacs"]["value"]
        
        effect = {"type": chosen}
        # We start the log here and append specifics based on the roll
        log_prefix = f"👑 **{char['name']}** invoked the **{chosen}** Zodiac: "

        if chosen == "Rat":
            effect["self_mult"] = 1 + vals[0]
            log = log_prefix + f"Gained a +{int(vals[0]*100)}% power surge!"
            
        elif chosen == "Ox":
            valid_opps = [i for i, c in enumerate(opponent_team_list) if c]
            if valid_opps:
                idx = random.choice(valid_opps)
                effect["target_opp_idx"] = idx
                effect["opp_mult"] = 1 - vals[1]
                log = log_prefix + f"Crushed **{opponent_team_list[idx]['name']}** (-{int(vals[1]*100)}% Power)!"
            else:
                log = log_prefix + "But there were no enemies to crush."
                
        elif chosen == "Tiger":
            effect["team_mult"] = 1 + vals[2]
            log = log_prefix + f"Roared, boosting the team's morale (+{int(vals[2]*100)}% Power)!"
            
        elif chosen == "Rabbit":
            effect["opp_team_mult"] = 1 - vals[3]
            log = log_prefix + f"Beguiled the enemy team (-{int(vals[3]*100)}% Total Power)!"
            
        elif chosen == "Dragon":
            effect["override_variance"] = vals[4]
            log = log_prefix + "Seized control of fate (Max Variance Locked)!"
            
        elif chosen == "Snake":
            effect["force_draw_on_loss"] = True
            log = log_prefix + "Lidless eyes watch... (Losses will become DRAWS)!"
            
        elif chosen == "Horse":
            effect["self_mult"] = 1 - vals[6][0]
            teammates = [i for i, c in enumerate(team_list) if c and c != char]
            if teammates:
                # Find the index in the original team_list
                t_idx = random.choice([i for i, c in enumerate(team_list) if c and c != char])
                effect["target_teammate_idx"] = t_idx
                effect["teammate_mult"] = 1 + vals[6][1]
                log = log_prefix + f"Sacrificed strength to empower **{team_list[t_idx]['name']}**!"
            else:
                log = log_prefix + "But there were no allies to empower."
                
        elif chosen == "Sheep":
            effect["sheep_logic"] = True
            log = log_prefix + "Mirrored the aura of the strongest foe!"
            
        elif chosen == "Monkey":
            valid_opps = [i for i, c in enumerate(opponent_team_list) if c]
            if valid_opps:
                idx = random.choice(valid_opps)
                effect["monkey_target_idx"] = idx
                log = log_prefix + f"Pranked **{opponent_team_list[idx]['name']}**, swapping power levels!"
            else:
                log = log_prefix + "But the prank failed."
                
        elif chosen == "Rooster":
            effect["team_mult"] = 1 + vals[7][0]
            effect["self_mult"] = 1 + vals[7][1]
            log = log_prefix + "The dawn awakens! Self and Team power increased!"
            
        elif chosen == "Dog":
            effect["dog_logic"] = True
            log = log_prefix + "Loyally copied the power of the strongest ally!"
            
        elif chosen == "Pig":
            effect["disable_random_opp_skill"] = True
            log = log_prefix + "Muddied the waters, disabling a random enemy skill!"

        return effect, log

    @staticmethod
    def apply_individual_battle_skills(base_power, char):
        """
        Calculates individual power modifiers and generates logs.
        Returns: (modified_power, list_of_log_strings)
        """
        tags = char.get('ability_tags', [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = []
        
        modified_power = base_power
        logs = []

        if "Lucky 7" in tags:
            if random.random() < 0.07:
                modified_power *= 8.77
                logs.append(f"✨ **{char['name']}** hit the Lucky 7 Jackpot (+777% Power)!")
            if random.random() < 0.77:
                modified_power += 7777
                logs.append(f"🍀 **{char['name']}** gained a Lucky 7 flat bonus (+7,777)!")

        if "Surge" in tags:
            mult = SKILL_DATA["Surge"]["value"]
            modified_power *= (1 + mult)
            logs.append(f"⚡ **{char['name']}** activated **Surge** (+{int(mult*100)}%)!")

        if "Golden Egg" in tags:
            if random.random() < 0.01:
                mult = SKILL_DATA["Golden Egg"]["value"]
                modified_power *= mult
                logs.append(f"🥚 **{char['name']}** hatched a **Golden Egg** ({mult}x Power)!")

        if "Berserk" in tags:
            if random.random() < 0.25:
                mult = SKILL_DATA["Berserk"]["value"]
                modified_power *= (1 + mult)
                logs.append(f"💢 **{char['name']}** went **Berserk** (+{int(mult*100)}%)!")

        if "The Joker" in tags:
            val = SKILL_DATA["The Joker"]["value"]
            if random.random() < 0.5:
                modified_power *= (1 + val)
                logs.append(f"🃏 **{char['name']}**'s Joker was a BUFF (+{int(val*100)}%)!")
            else:
                modified_power *= (1 - val)
                logs.append(f"🃏 **{char['name']}**'s Joker was a DEBUFF (-{int(val*100)}%)!")

        return modified_power, logs

    @staticmethod
    def apply_team_battle_mods(team_power, enemy_active_skills):
        """
        Calculates team-wide power modifiers (like debuffs from the enemy).
        Returns: (final_power, list_of_log_strings)
        """
        final_power = team_power
        logs = []

        if "Guard" in enemy_active_skills:
            val = SKILL_DATA["Guard"]["value"]
            final_power *= (1 - val)
            logs.append(f"🛡️ Enemy **Guard** reduced total power by {int(val*100)}%!")

        return final_power, logs

    @staticmethod
    def handle_kamikaze(opponent_team_list, team_active_skills):
        """
        Handles the Kamikaze skill.
        Returns: (list_of_target_indices_to_ignore, list_of_logs)
        """
        killed_indices = []
        logs = []
        if "Kamikaze" in team_active_skills and opponent_team_list:
            count = team_active_skills["Kamikaze"]
            available = [i for i, c in enumerate(opponent_team_list) if c is not None]
            
            for _ in range(count):
                if not available: break
                target_idx = random.choice(available)
                killed_indices.append(target_idx)
                logs.append(f"💥 **Kamikaze** eliminated **{opponent_team_list[target_idx]['name']}**!")
                available.remove(target_idx)
        
        return killed_indices, logs

    @staticmethod
    def handle_revive(won_battle, team_active_skills, snake_trap=False):
        """
        Determines the final battle outcome, checking for Revive or Snake Zodiac.
        Returns: (result_string, list_of_logs)
        """
        if not won_battle:
            if snake_trap:
                return "DRAW", ["🐍 The **Snake Zodiac** trap triggered! The defeat was forced into a **DRAW**."]
            
            if "Revive" in team_active_skills:
                chance = SKILL_DATA["Revive"]["value"]
                if random.random() < chance:
                    return "DRAW", [f"💖 **Revive** triggered! The defeat was turned into a **DRAW**."]
        
        return ("WIN" if won_battle else "LOSS"), []