# Coaching rubric

Checks to run on each game, what to look for, and how to judge them. Examples come from
real games that shaped these rules.

## Data blind spots (state these when a claim depends on them)

- Positions are sampled roughly every 15 seconds and only for heroes that recently dealt
  or took damage. A hero missing from a snapshot was not necessarily absent.
- Ability usage, heroic casts, and what CC landed are not in tracker events. "Kel'Thuzad's
  root probably set this up" is an inference from who was in the kill.
- Some maps emit no objective events (see maps.md).
- Score stats are end-of-game totals. Auriel's healing is inflated by stored damage, so
  don't compare healers naively.

## Player-level checks

**1. Solo exposure (the most common avoidable death).** Was the player the only ally
within ~20 units while 2+ enemies were near? Common forms:
- solo soaking a lane against a duo (Braxis 5:20, Dragon Shire 6:36 vs Tychus + Auriel)
- staying in a lane after the lane partner hearthed (Garden 6:05, Tyrael hearthed)
- walking back to a lane alone after respawning (Dragon Shire 11:00)
- carrying an objective item alone (Warhead nuke dropped at 4:58)
Judge: avoidable. Coach the trigger: "when your partner leaves, you leave."

**2. Frontline distance.** At each death, how far was the team's tank/bruiser? 30+
units is a flag (Infernal Shrines: Leoric 38-87 units away at three deaths). If the
player died next to the tank and the tank also died, the death is mostly a lost fight,
not a positioning error (Volskaya: three deaths beside Tyrael).

**3. First down.** Was the player the first of their team to die in a fight? Once is
noise; 2+ times in a game means they are standing too far forward. Healer-first deaths
usually lose the fight.

**4. Enemy-half deaths.** Deaths beyond the midline, especially near enemy structures.
Key pattern: diving the enemy base while ahead (Hanamura 15:25 and again 16:55 at the
same spot). Coach: when ahead, siege with camps and objectives, let the tank lead, and
the healer is the brake.

**5. Pre-objective deaths.** Death within ~45s before an objective activates puts the
team down a body at the objective (Dragon Shire 10:39 before the second Knight).

**6. Recurring killers.** One or two enemies in most deaths. Distinguish the hero who
stuck to the player (Illidan, Greymane, Valeera) from the one enabling it (Kel'Thuzad
was in all six Infernal Shrines deaths). Give hero-specific counterplay: walk toward the
team, place slows/roots on the diver, save escapes.

**7. Absent from lost fights.** Team lost 2+ heroes while the player was alive and 40+
units away. Flags in the first ~4 minutes are usually normal laning; later ones usually
mean the player was soaking or wandering while the team fought without them
(Braxis 4:57-5:20: team lost three up top while the player solo-soaked bottom).

**8. Teamfight share.** For healers, teamfight healing under ~15% of total suggests
being out of range when fights start, but check context first: very short decisive fights
(a winning team) or fights lost instantly both produce low numbers.

## Team-level checks (explain them, don't blame the player)

**A. Lane assignments, 1:30-5:00.** Use `positions`. Look for an enemy hero alone in a
lane with nobody matching them (Volskaya: Ragnaros alone top, four allies mid; he took a
fort at 3:41 and the minion XP gap followed). If the player could have covered or
pinged it, say so.

**B. XP source.** From the timeline's XP table: a MinionXP gap means soak/lanes were
lost; a HeroXP gap means fights were lost; StructureXP means objectives/pushes. Braxis
showed a HeroXP gap (zero team kills from 2:00 to 10:00), Volskaya a MinionXP gap.

**C. Level milestones.** Who hit 10/16/20 first and by how much. 30+ seconds behind at a
talent tier means objective fights near that time were uphill; conceding was often right.

**D. Objective outcomes.** Count wins per side. A streak of lost objectives plus deaths
just before them means the team was fighting down bodies.

**E. Body count.** Abathur, split-pushers, and dead allies make objective fights 4v5 or
worse. If the team forced those fights anyway, the coaching point is to concede and take
camps or soak instead.

## Weighing it

Lead with what decided the game, then the player's share of it. In a loss driven by team
macro the player's best lesson is usually still one avoidable death type. In a win, look
for sloppiness after taking a lead. Never pad with generic advice; every point needs a
timestamp or a number behind it.
