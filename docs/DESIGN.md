# Plasticify - how it works

Plasticify is a standalone override pack: every vanilla texture under
`textures/block`, `textures/entity`, `textures/item` and `textures/models` is
replaced by a flat, glossy plastic version, with LabPBR material maps so shaders
light it as smooth plastic. It is deliberately not a total conversion - it only
flattens what can be flattened without losing information.

Current build: **2790 vanilla textures** - block 1269, entity 725, item 796 -
built into **8727 pack files** (1.6 MiB), with no missing albedo, `_n` or `_s`.

## Scope

Replaced: everything under the four roots above, plus a flat `_n`/`_s` pair for
each texture and a copy of the vanilla `.mcmeta` so animations keep their frame
count and speed (118 metadata files, 56 animated textures).

Left alone on purpose: `textures/gui`, `font`, `colormap`, `environment`, `map`,
`misc` and `painting`. Menus, fonts and maps stay readable, and the sky and
colourmaps stay vanilla.

## The recipe

The albedo is a **quantised** version of the vanilla texture, not a blur and not
a single colour. The palette size scales with how much shape the texture has,
because one flat colour makes a block impossible to tell from its neighbour:

| shape score (`structure`) | palette |
|---|---|
| < 3 | 2 |
| < 10 | 3 |
| < 20 | 4 |
| < 30 | 5 |
| < 45 | 6 |
| otherwise | 8 |
| **contrast `d98 >= 110`** | **keep the vanilla texture, byte-for-byte** |
| **pinned family** (see below) | the pinned size, or `keep` |

Typical landings: stone 2.55 -> 2; cobblestone 5.7 and resin 9.2 -> 3; sandstone
7.2 -> 3; planks 13.8 and stone bricks 16.5 -> 4; copper grate 19.2 -> 4 (its
holes survive); note block 20.8 -> 5; birch door 44 -> 6; carved pumpkin 31 and
TNT 62 -> keep.

Two metrics drive it, both measured over visible pixels only:

* `structure` - p90 of the blurred deviation from the mean: coherent shape, as
  opposed to per-pixel speckle.
* `d98` - p98 of the distance from the dominant colour: how much *deliberate*
  contrast the design has.

`d98 >= 110`, not `structure`, is what protects the artwork. Pumpkin faces (115),
TNT's letters (229), target rings (179), filled-map markings (255) and item icons
(129+) all have thin shapes, so a shape-based keep test flattens them - that
mistake was made once and reverted.

Before quantising, every texture gets the tolerance filter: 3x3, tolerance 28,
applied per frame. The palette itself is one adaptive median-cut palette for the
whole atlas, built from visible pixels only, so animation frames never flicker.
The recipe is decided once per texture, with the filename available.

## Pins

`PINS` in `build.py` is a list of `(fnmatch pattern, palette size or None for
keep)` rules. They exist because the families interleave and no global threshold
can separate them: a birch door scores 44 while a spruce door scores 13; diorite
scores 110 (keep) while granite scores 82 (3 colours). Both are "ordinary" to a
player. When a family lands wrong, pin it rather than moving a threshold.

| pattern | treatment | why |
|---|---|---|
| `block/*_sign*`, `item/*_sign*` | 3 | plank boards; the shape comes from the model |
| `block/*_door_*`, `item/*_door*`, `block/*_trapdoor`, `item/*trapdoor*`, `block/*_shelf` | 4 | same, with a frame worth one extra tone |
| `block/*_bars`, `item/*_bars`, `block/*_chain`, `item/*_chain` | 4 / 3 | thin metal |
| `block/prismarine*` | 3 | plain stone-like material |
| `block/*_ore` | 4 | mineral specks read as flat patches |
| `block/diorite`, `amethyst_block`, `budding_amethyst`, `redstone_block`, `magma`, `ancient_debris_top`, `melon_side`, `honeycomb_block`, `cactus_side` | 3 | plain materials the contrast test misroutes into keep |
| `entity/<mob>/*` - the 59 folders in `MOB_DIRS` | keep | see below |

### Mobs are gloss-only

A mob texture is a drawing: eyes, snout, fur markings. Quantising a face drawn
with 20-50 tones down to 2-6 erases exactly those details (cat 12 files, horse
23, wolf 15, villager 9, rabbit 10, fish 11, pig 5 were affected). Every living
entity - all 59 folders, 456 textures - is therefore pinned to `keep`: the
albedo ships byte-for-byte vanilla, and the flat `_n`/`_s` pair is still written,
so mobs are **glossy, just never flattened**.

Block-like entity textures are not mobs and stay on the ladder: chests, banners,
shields, boats, minecarts, beds, decorated pots, projectiles, tridents, armour
and equipment, bells, beacons, conduits, enchanting table, end crystal and
portal, fishing hooks, lead knots, experience orbs.

`verify.py` enforces this: for every mob texture the albedo must equal vanilla
bytes and `_n`/`_s` must equal `N_FLAT`/`S_FLAT`.

## Material maps

* `_n` = `(127, 127, 255, 255)` - a flat normal, full height.
* `_s` = `(208, 20, 0, 255)` - roughness `(47/255)^2 = 0.034`, F0 7.8%, no
  porosity, no emission.

Both are written at the albedo's dimensions, and the vanilla `.mcmeta` is copied
onto all three files so animated textures stay in step.

## Recipes that were rejected

| recipe | verdict |
|---|---|
| `mean + 0.25 * (blur(original, r) - mean)` | muddy smear: blur keeps the low frequencies that carry no shape and destroys the high ones that carry all of it |
| median 3x3 / 5x5 denoise | eats 1 px lines - wiped the target rings and the glyphs off `enchanting_table_side` |
| tolerance filter r=2 | merges books and holes at 16 px |
| single flat colour per block | blocks become indistinguishable from their neighbours |
| flat gated on `uni32 >= 0.80` | cobblestone is only 63% one colour because of its mortar, so it never flattened |
| flat gated on `structure < 18` alone | flattened TNT's bottom face and the item door icons |
| "specks vs drawing" density signal | no separation: `filled_map_markings` scores 0.086, below every plain material (diorite 0.43, granite 0.15, cactus 0.09) - pins do this job instead |

Implementation traps encoded in `build.py`:

* **Palette from visible pixels only.** `Image.quantize` counts alpha padding as
  real pixels, so cut-outs spend palette entries on transparent black and round
  their real colours away.
* **Squared-distance mapping must be int32.** `255^2 = 65025` overflows int16 and
  silently picks the wrong nearest colour.
* Textures already at or below their palette size are returned byte-identical.
* Invisible pixels are pre-filled with the mean visible colour before filtering,
  so nothing bleeds a black halo into the mipmaps. Alpha itself is never touched.

## House rules

* `pack_format` / `min_format` / `max_format` = 88 (Minecraft Java 26.2). Never
  add `supported_formats`.
* JSON is written with 4-space indent, `\n` endings and no BOM.
* Never write into the Minecraft install. The build writes into this repo
  (`--out DIR` for a throwaway build) and the pack folder or `dist/*.zip` is
  copied into `resourcepacks` by hand - a **folder-level** copy, because a
  wildcard `-Recurse` copy drops a level and the pack then loads empty.
* Load order in game: Plasticify goes **below** any pack with authored models or
  textures. That pack wins where it has content, Plasticify fills the rest.
* `README.md` is player-facing and deliberately non-specific: no pack names, no
  metric names, no per-family pin lists, no build internals - those live here.
  The `pack.mcmeta` description stays one line, `Plasticify <version> | by
  <author>`; `VERSION` in `build.py` is the constant to bump for a release, and
  `release.py` reads it back out of the description to name the zip.
* `pack.png` is **authored**, not generated: the shipped icon is a 512 px
  drawing that `make_icon()` (128 px) does not reproduce, so a build writes an
  icon only when the pack has none. `build.py --icon` is the explicit redraw.

## Tuning

The knobs are at the top of `build.py`: `PALETTE_LADDER` (structure -> palette
size), `PALETTE_TOP`, `T_KEEP` (contrast floor for keep), `SIGMA_T`/`SIGMA_R` (the
quantise filter) and `PINS`.

Run `build.py --list` after any change: the split lands in
`_analysis/recipe_split.md` for review, and `entity_split.py` shows the entity
tree by folder. Keep the previous split as `_analysis/recipe_split_prev.csv` to
diff two builds and get the exact change list.
