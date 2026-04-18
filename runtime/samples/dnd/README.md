# D&D Samples

These are user-facing example programs built on `stdlib/dnd`.

- `combat_profiles.dice`: compare a small set of common combat options as full damage distributions
- `strategy_heatmap.dice`: sweep armor class and compare several martial and caster plans
- `ability_scores_4d6h3.dice`: summarize classic 4d6-drop-lowest ability score generation
- `agonizing_eldritch_blast_vs_ac.dice`: compare plain, Agonizing, and Hexed blast packages across armor classes
- `eldritch_blast_debug.dice`: inspect how plain blast, Agonizing Blast, and Hex reshape the beam and full-action profiles
- `cantrip_progression.dice`: compare several no-resource damage options across levels
- `fireball_party_total.dice`: sum expected fireball damage across a party with mixed save bonuses
- `greatsword_gwf_vs_ac.dice`: compare heavy melee packages including Great Weapon Fighting and Great Weapon Master
- `hunters_mark_longbow_vs_ac.dice`: compare ranged damage packages across armor classes
- `magic_missile_vs_slot.dice`: show exact magic missile scaling by slot level
- `martial_tradeoffs.dice`: compare blessing, fighting styles, power attacks, and mark effects across AC
- `spell_slot_showdown.dice`: compare how common spells scale as slot level rises
- `discussions/`: recreate online D&D math discussions as exact `dice` sample programs, including feat tradeoffs, action-economy break-even points, and concentration edge cases
  Prefer keeping both the executable data surface and the rendered report in the same `.dice` file when that stays readable.
  If a discussion report truly needs extra orchestration beyond the report DSL, use a sibling `*_report.py` beside the sample rather than centralizing that logic elsewhere.

The thin one-scenario regression fixtures that used to live here now belong under `tests/`.
The goal of this directory is readability: each file should be substantial enough to show how
someone might actually use the packaged D&D helpers.
