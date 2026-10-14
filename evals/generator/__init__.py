"""Seeded synthetic persona generator (docs/09 §3.1).

Deterministic: identical (dataset, seed, GENERATOR_VERSION) produces byte-identical files. Every
random draw comes from numpy's PCG64, split per layer with SeedSequence so changing one layer
does not reshuffle the others. All people, banks and amounts are fictional.
"""

GENERATOR_VERSION = "gen-1.1.0"
PRIMARY_SEED = 1729
