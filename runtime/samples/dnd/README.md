# D&D Samples

These are user-facing example programs built on `stdlib/dnd`.

- `combat_profiles.dice`: compare a small set of common combat options as full damage distributions
- `strategy_heatmap.dice`: sweep armor class and compare several martial and caster plans
- `ability_scores_4d6h3.dice`: summarize classic 4d6-drop-lowest ability score generation

The thin one-scenario regression fixtures that used to live here now belong under `tests/`.
The goal of this directory is readability: each file should be substantial enough to show how
someone might actually use the packaged D&D helpers.
