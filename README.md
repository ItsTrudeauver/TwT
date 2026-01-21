# TwT Bot

TwT Bot is a dynamic RPG and Gacha agent designed for high-engagement Discord communities. It features a unique character ranking system based on global popularity.

## Quick Links

* [Command Index](https://www.google.com/search?q=%23command-index)
* [Daily Cycles](https://www.google.com/search?q=%23daily-cycles)
* [Expedition System (Passive Income)](https://www.google.com/search?q=%23expedition-system-passive-income)
* [Gacha & Inventory](https://www.google.com/search?q=%23gacha--inventory)

---

## Command Index

### Economy & Profile

* **!gems** / **!pc** / **!wallet**: View your current gem balance.
* **!profile**: View your overall account stats and rank.
* **!ranks**: View the global leaderboard of the wealthiest players.

### Expedition System

* **!set_expedition** / **!se**: Assign units to your expedition team.
* **!ex start**: Start the passive income timer.
* **!ex claim**: Collect your gems.
* **!ex status**: View current mission progress.

### Battle System

* **!set_team_battle** / **!stb**: Define your 5-man combat squad.
* **!battle <@user>**: Challenge a player to a PVP standoff.
* **!battle <difficulty>**: Challenge an NPC for daily tasks.

### Gacha & Collection

* **!pull <1/10>**: Summon new characters.
* **!starter**: Claim your starting units.
* **!inventory** / **!inv**: Browse your collection.
* **!view <id>**: Inspect a character's skills and full art.
* **!lock** / **!unlock**: Manage character protection.
* **!mass_scrap** / **!ms**: Recycle all unlocked R-Rank units.

### Daily Tasks

* **!checkin**: Claim daily gems.
* **!tasks**: View combat objectives.
* **!claim <difficulty>**: Collect gems for defeated NPCs.

---

## Daily Cycles

Routine objectives to maintain your gem flow.

### The Daily Check-in

Every 24 hours, you can claim a baseline stimulus to keep your account active.

* **Command**: `!checkin`
* **Reward**: 1,500 Gems

### Combat Tasks

The bot provides a tiered system of NPC challenges. To receive these rewards, you must first defeat the NPC in battle and then manually claim the bounty.

**The Workflow**

1. View available challenges: `!tasks`
2. Enter the fight: `!battle <difficulty>`
3. Secure the gems: `!claim <difficulty>`

**Reward Breakdown**

* **Easy**: 500 Gems (Requires defeating 5 R-Rank units)
* **Normal**: 1,000 Gems (Requires defeating 3 R and 2 SR units)
* **Hard**: 1,500 Gems (Requires defeating 5 SR-Rank units)
* **Expert**: 2,500 Gems (Requires defeating 2 SSR and 3 SR units)
* **Hell**: 5,000 Gems (Requires defeating the top 50 ranked SSR units)

**Note:** All tasks reset every 24 hours. You must complete the battle before the claim command will function.

---

## Expedition System (Passive Income)

Expeditions are the primary engine for generating wealth. Unlike active tasks, your earnings scale based on real-world time and the specific skills of the characters you own.

### Setting the Squad

Your Expedition Squad is separate from your Battle Squad. You can assign up to 5 characters to this roster.

**The Setup Command**
Use `!set_expedition` (or `!se`) followed by the unique IDs from your inventory.

> `!se 102 45 8 201 55`

### Managing the Mission

Once your team is assigned, use the `!ex` subcommands to handle the mission:

* **!ex start**: Begins the expedition timer.
* **!ex status**: Checks your current elapsed time and estimated gem yield.
* **!ex claim**: Ends the mission and deposits gems.

**Warning:** Missions must run for a minimum of 60 seconds. Claiming early will result in 0 gems and reset your timer.

### The Multiplier Meta

Your final payout is calculated by stacking three distinct types of bonuses.

**Active Skill: Hardworker**

* **Bonus**: +15% per unit.
* **Requirement**: The character must be physically assigned to the Expedition Squad.
* **Effect**: If 5 units with this skill are deployed, you gain a +75% bonus.

**Global Skill: Master of Coin**

* **Bonus**: +10% per unit.
* **Requirement**: None. This is a passive global buff.
* **Effect**: As long as these units are in your inventory, the bonus stacks. You do not need to deploy them.

**Time Bonus: The Long Road**

* **Bonus**: Scales up to +24%.
* **Requirement**: Time elapsed.
* **Effect**: Efficiency increases hourly. To reach the maximum 24% bonus, the expedition must run for a full 24 hours.

---

## Gacha & Inventory

How to expand your collection and recycle junk units.

### Pulling Units

Gacha pulls are the only way to acquire new units and find characters with the "Master of Coin" global buff.

* **!pull 1**: Costs 1,000 Gems.
* **!pull 10**: Costs 10,000 Gems.
* **!starter**: A one-time command that gives new players 10 units (1 guaranteed SSR).
* **!banner**: Displays the current rate-up characters and the expiration time of the current event.

### Inventory Management

With a 5,000+ character database, your inventory will fill up quickly. Managing the "In and Out" is vital.

**Protecting Assets**
Before cleaning your inventory, lock your most valuable units (SSRs and those with Master of Coin).

* **!lock <id>**: Prevents the unit from being scrapped.
* **!unlock <id>**: Removes protection.
* **!view <id>**: Shows the character's art, rarity, and skill tags.

**The Mass Scrap (The "Out")**
Use the `!mass_scrap` (or `!ms`) command to instantly clean your inventory.

* **Logic**: This command automatically deletes every **unlocked R-Rank unit** in your collection.
* **Payout**: You receive a partial gem refund for every unit scrapped.

**Important:** Always lock your R-rank units that have the **Master of Coin** skill. If they are unlocked, `!mass_scrap` will delete them, and you will lose your global passive income bonus.