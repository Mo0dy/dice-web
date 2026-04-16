# D&D Sample Library

Executable sample programs for stressing the current dice language with D&D-like use cases.

- `at_table/`: concrete actions you might evaluate during play
- `analysis/`: sweep-based setup comparisons and expected-value views
- `lib/`: reusable helper libraries imported by the sample programs
- `stdlib/` equivalents are available to end users through imports such as `import "std:dnd/weapons.dice"`

The mechanics are intentionally approximate. Their main purpose is to exercise the language surface and reveal modeling gaps.

The samples now intentionally exercise:

- relative `import "..."` for reusable combat helpers inside the sample tree
- packaged stdlib imports such as `import "std:dnd/weapons.dice"` for reusable shared helpers
- `# ...` comments inside `.dice` files
- reusable shared-roll crit helpers built on `match ... as ...`
- `repeat_sum(n, expr)` for repeated independent attacks or beams
- direct Bernoulli counting patterns such as `repeat_sum(6, score >= target)` without `-> 1 | 0`
- advantage via higher-level helpers such as `reckless_great_weapon_master(...)`
- keep-high syntax through `4 d 6 h 3` stat rolls
- all current `stdlib/dnd/weapons.dice` and `stdlib/dnd/spells.dice` helper entry points
- sweep-based build analysis across AC, save bonuses, or dart counts
