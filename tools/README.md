# Plasticify tools

Scripts that build, check and pack the resource pack. Each one treats **this
repo as the pack** (the folder holding `pack.mcmeta`, one level up) and pulls the
vanilla originals from a **Minecraft client jar**.

## Setup

```
python -m pip install -r tools/requirements.txt
```

The client jar is found automatically - run `python tools/common.py` to see which
one. To pin a specific jar:

```
python tools/build.py --jar "C:\path\to\client.jar"
PLASTICIFY_JAR=C:\path\to\client.jar       # or `export` on macOS/Linux
```

## The scripts

| script | job |
|---|---|
| `common.py` | shared context: pack root, jar discovery, vanilla texture list |
| `build.py` | draws the pack - flat plastic albedo plus `_n`/`_s` maps into `assets/` |
| `verify.py` | the gate: full coverage, PBR on every texture, mobs gloss-only, metadata |
| `quality.py` | regression check: per-texture colour shift against vanilla |
| `calibrate.py` | metric table for curated flat / quantise / keep textures |
| `tiers.py` | QA contact sheet: named blocks, mobs, one rung of the ladder at a time |
| `entity_split.py` | per-folder entity recipe split - kept vs quantised, by folder |
| `release.py` | packs `dist/Plasticify-<version>.zip` for upload |

A full run, from the repo root:

```
python tools/build.py --list      # measure; writes _analysis/recipe_split.md, draws nothing
python tools/build.py --force     # build the pack (about 5 seconds)
python tools/verify.py            # coverage + PBR + the mob gloss-only gate
python tools/quality.py           # colour-shift regression
python tools/tiers.py             # QA sheet -> _analysis/tiers.png
python tools/release.py           # dist/Plasticify-<version>.zip
```

## Output

The build output *is* this repo: `assets/`, `pack.mcmeta`, `pack.png`,
`README.md`. Dev by-products land in `_analysis/` and releases in `dist/`; both
are git-ignored.

`pack.png` is authored rather than generated - a build writes an icon only when
the pack has none, and `build.py --icon` is the explicit redraw. `build.py --out
DIR` builds somewhere else, which is the safe way to try a change without
touching the pack.

How the recipe works, and why: [../docs/DESIGN.md](../docs/DESIGN.md).
