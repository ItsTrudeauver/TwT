import random
import json
from core.skills import SKILL_DATA

class SkillHandler:
    @staticmethod
    def get_active_skills(character_list, context='b'):
        """
        Filters a list of characters to find active skills based on context (b/e/g).
        Respects 'overlap' and 'stackable' rules.
        Returns: { "SkillName": count }
        """
        active_effects = {}
        seen_non_overlap = set()

        for char in character_list:
            if not char: continue
            
            # Ability tags are stored as a JSON list in the DB
            tags = char.get('ability_tags', [])
            if isinstance(tags, str):
                tags = json.loads(tags)

            for skill_name in tags:
                config = SKILL_DATA.get(skill_name)
                if not config or config['applies_in'] not in [context, 'g']:
                    continue

                # Rule: Overlap (Is this skill allowed to exist twice on the team?)
                if not config['overlap'] and skill_name in seen_non_overlap:
                    continue
                seen_non_overlap.add(skill_name)

                # Rule: Stackable (Does having 2 actually double the effect?)
                if config['stackable']:
                    active_effects[skill_name] = active_effects.get(skill_name, 0) + 1
                else:
                    active_effects[skill_name] = 1
        
        return active_effects

    # --- BATTLE PHASE 1: INDIVIDUAL POWER ---
    
    @staticmethod
    def apply_individual_battle_skills(base_power, char):
        """Processes skills that modify a specific character's power."""
        tags = char.get('ability_tags', [])
        if isinstance(tags, str): tags = json.loads(tags)
        
        modified_power = base_power

        if "Surge" in tags:
            modified_power *= (1 + SKILL_DATA["Surge"]["value"])

        if "Golden Egg" in tags:
            if random.random() < 0.01: # 1% chance
                modified_power *= SKILL_DATA["Golden Egg"]["value"]

        if "Berserk" in tags:
            if random.random() < 0.25: # 25% chance
                modified_power *= (1 + SKILL_DATA["Berserk"]["value"])

        if "The Joker" in tags:
            # 50/50 chance to either buff by 40% or debuff by 40%
            multiplier = 1 + SKILL_DATA["The Joker"]["value"] if random.random() < 0.5 else 1 - SKILL_DATA["The Joker"]["value"]
            modified_power *= multiplier

        return modified_power

    # --- BATTLE PHASE 2: TEAM MODIFIERS ---

    @staticmethod
    def apply_team_battle_mods(opponent_power, team_active_skills):
        """Processes skills that affect the enemy or the whole team."""
        final_opp_power = opponent_power

        # Guard: Deduct 10% from opponent
        if "Guard" in team_active_skills:
            # Note: Overlap/Stackable is handled by get_active_skills
            # If stackable was True, we'd multiply by count. Since False, we do it once.
            final_opp_power *= (1 - SKILL_DATA["Guard"]["value"])

        return final_opp_power

    # --- BATTLE PHASE 3: UTILITY & STANDOFF ---

    @staticmethod
    def handle_kamikaze(opponent_team_list, team_active_skills):
        """
        Kamikaze: Removes random enemies from the calculation.
        Returns a list of indices to IGNORE in the opponent team.
        """
        killed_indices = []
        if "Kamikaze" in team_active_skills and opponent_team_list:
            count = team_active_skills["Kamikaze"] # Number of triggers
            available_indices = [i for i, c in enumerate(opponent_team_list) if c is not None]
            
            for _ in range(count):
                if not available_indices: break
                target = random.choice(available_indices)
                killed_indices.append(target)
                available_indices.remove(target)
        
        return killed_indices

    @staticmethod
    def handle_revive(won_battle, team_active_skills):
        """Revive: 25% chance to force a DRAW on a LOSS."""
        if not won_battle and "Revive" in team_active_skills:
            if random.random() < SKILL_DATA["Revive"]["value"]:
                return "DRAW"
        return "WIN" if won_battle else "LOSS"

    # --- EXPEDITION LOGIC ---

    @staticmethod
    def calculate_expedition_multiplier(team_list, account_wide_chars):
        """
        Calculates total multiplier for expeditions.
        Combines 'e' (team) and 'g' (global) skills.
        """
        multiplier = 1.0
        
        # 1. Team-based (Hardworker)
        team_skills = SkillHandler.get_active_skills(team_list, context='e')
        if "Hardworker" in team_skills:
            multiplier += (SKILL_DATA["Hardworker"]["value"] * team_skills["Hardworker"])

        # 2. Account-wide (Master of Coin)
        # Note: This requires passing ALL user characters, or a pre-filtered list
        global_skills = SkillHandler.get_active_skills(account_wide_chars, context='g')
        if "Master of Coin" in global_skills:
            multiplier += (SKILL_DATA["Master of Coin"]["value"] * global_skills["Master_of_Coin"])

        return multiplier