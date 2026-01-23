class BattleContext:
    """
    Holds the state of the battle (teams, logs, suppressed skills, modifiers).
    Passed to every skill so they can read/write the battle state.
    """
    def __init__(self, attacker_team, defender_team):
        self.teams = {
            "attacker": attacker_team,
            "defender": defender_team
        }
        # Logs organized by [Side][SlotIndex]
        # SlotIndex None implies a team-wide/misc log
        self.logs = {
            "attacker": {i: [] for i in range(len(attacker_team))},
            "defender": {i: [] for i in range(len(defender_team))}
        }
        self.misc_logs = {"attacker": [], "defender": []}
        
        # Suppressed skills (set of strings)
        self.suppressed = {"attacker": set(), "defender": set()}
        
        # Numeric Modifiers
        # multipliers[side][slot] starts at 1.0
        self.multipliers = {
            "attacker": {i: 1.0 for i in range(len(attacker_team))},
            "defender": {i: 1.0 for i in range(len(defender_team))}
        }
        # Flat bonuses applied after multipliers
        self.flat_bonuses = {
            "attacker": {i: 0 for i in range(len(attacker_team))},
            "defender": {i: 0 for i in range(len(defender_team))}
        }
        
        # Global Flags (e.g. for Snake Zodiac trap)
        self.flags = {}

    def add_log(self, side, idx, message):
        """Adds a log message to the battle record."""
        if idx is not None and 0 <= idx < 5:
            self.logs[side][idx].append(message)
        else:
            self.misc_logs[side].append(message)

    def suppress_skill(self, target_side, skill_name):
        """Marks a skill as disabled for the target side."""
        self.suppressed[target_side].add(skill_name)

    def is_suppressed(self, side, skill_name):
        """Checks if a skill is currently disabled."""
        return skill_name in self.suppressed[side]

    def get_team(self, side):
        return self.teams[side]

    def get_enemy_side(self, my_side):
        return "defender" if my_side == "attacker" else "attacker"

class BattleSkill:
    """Abstract base class for all skills."""
    def __init__(self, name, owner_data, owner_idx, side, config_value):
        self.name = name
        self.owner = owner_data # The character dictionary
        self.idx = owner_idx    # 0-4
        self.side = side        # "attacker" or "defender"
        self.val = config_value # The value from SKILL_DATA (e.g. 0.25)
        self.enemy_side = "defender" if side == "attacker" else "attacker"

    async def on_battle_start(self, ctx: BattleContext):
        """
        Phase 1: Triggered before any calculations.
        Used for: Disabling skills, setting initial debuffs (Onyx Moon), Zodiac rolls, Kamikaze.
        """
        pass

    async def get_power_modifier(self, ctx: BattleContext, current_base_power):
        """
        Phase 2: Returns a multiplier for THIS unit.
        Used for: Simple buffs (Surge), Conditional buffs (Amber Sun).
        Returns: float (multiplier)
        """
        return 1.0

    async def on_post_power_calculation(self, ctx: BattleContext, final_powers):
        """
        Phase 3: Triggered after base power * multipliers is done, but before Team aggregation.
        Used for: Swapping power (Monkey), Copying power (Dog), Setting fixed power (Sheep).
        final_powers is a dict: {'attacker': [p1, p2...], 'defender': [p1, p2...]}
        """
        pass

    async def on_battle_end(self, ctx: BattleContext, result):
        """
        Phase 4: Triggered after win/loss determination.
        Used for: Revive, Snake Zodiac (forced Draw).
        Returns: New outcome string ("WIN", "LOSS", "DRAW") or None.
        """
        return None