"""QA contact sheet for the scaled-quantisation build.

Section 1: the blocks called out by name.
Section 2: the mobs, which must come out pixel-identical to vanilla (gloss only).
Section 3: each rung of the palette ladder - highest structure first, i.e. the
           members closest to needing the next rung up.
Section 4: keep-tier boundary cases, closest to the quantise threshold first.

Vanilla is on the left of each cell and the built texture on the right, on a
checkerboard so cut-outs are visible.

    python tools/build.py --list      # writes the CSV this reads
    python tools/tiers.py             # -> _analysis/tiers.png
"""
import csv
import io
import os

from PIL import Image, ImageDraw

from build import MOB_DIRS
from common import ANALYSIS, ROOT, read_vanilla

PACK = os.path.join(ROOT, "assets", "minecraft", "textures")
CSV  = os.path.join(ANALYSIS, "recipe_split.csv")
OUT  = os.path.join(ANALYSIS, "tiers.png")
CELL = 150

NAMED = [
    "block/oak_sign.png", "block/oak_hanging_sign.png", "block/birch_sign.png",
    "block/pale_oak_sign.png", "block/bamboo_sign.png", "block/spruce_sign.png",
    "block/prismarine.png", "block/prismarine_bricks.png", "block/dark_prismarine.png",
    "entity/skeleton/skeleton.png", "entity/skeleton/wither_skeleton.png",
    "entity/skeleton/stray.png", "entity/skeleton/bogged.png",
    "block/cobblestone.png", "block/resin_block.png", "block/sandstone.png",
    "block/stone_bricks.png", "block/oak_planks.png", "block/granite.png",
    "block/diorite.png", "block/copper_grate.png", "block/furnace_front.png",
    "block/carved_pumpkin.png", "block/tnt_side.png", "item/diamond_sword.png",
]

MOBS = [
    "entity/cat/cat_tabby.png", "entity/horse/horse_white.png",
    "entity/wolf/wolf.png", "entity/villager/villager.png",
    "entity/rabbit/rabbit_brown.png", "entity/pig/pig_temperate.png",
    "entity/fish/cod.png", "entity/fish/tropical_a.png",
    "entity/spider/spider.png", "entity/copper_golem/copper_golem.png",
    "entity/sheep/sheep.png", "entity/zombie/zombie.png",
    "entity/enderman/enderman.png", "entity/creeper/creeper.png",
    "entity/tadpole/tadpole.png",
]


def vanilla(rel):
    return Image.open(io.BytesIO(read_vanilla(rel))).convert("RGBA")


def built(rel):
    path = os.path.join(PACK, rel.replace("/", os.sep))
    return (Image.open(path).convert("RGBA") if os.path.exists(path)
            else Image.new("RGBA", (16, 16), (255, 0, 255, 255)))


def first_frame(im):
    """Animated atlases are square frames stacked vertically."""
    w = im.size[0]
    return im.crop((0, 0, w, min(im.size[1], w)))


def tile(im, cell=CELL):
    """One texture, nearest-neighbour upscaled, centred on a checkerboard."""
    im = im.convert("RGBA")
    bg = Image.new("RGBA", (cell, cell), (24, 24, 28, 255))
    for y in range(0, cell, 10):
        for x in range(0, cell, 10):
            if (x // 10 + y // 10) % 2:
                bg.paste((50, 50, 56, 255), (x, y, min(x + 10, cell), min(y + 10, cell)))
    w, h = im.size
    s = max(1, int(cell / max(w, h)))
    up = im.resize((w * s, h * s), Image.NEAREST)
    if max(up.size) > cell:
        f = cell / max(up.size)
        up = up.resize((max(1, int(up.size[0] * f)), max(1, int(up.size[1] * f))),
                       Image.NEAREST)
    bg.alpha_composite(up, (max(0, (cell - up.size[0]) // 2),
                            max(0, (cell - up.size[1]) // 2)))
    return bg


def main():
    rows = list(csv.DictReader(io.open(CSV, encoding="utf-8")))
    by_name = {r["texture"]: r for r in rows}
    mobs = sum(1 for r in rows if r["texture"].startswith("entity/")
               and r["texture"].split("/")[1] in MOB_DIRS)

    sheet_rows = [("head", "The blocks you named   |   vanilla  ->  built")]
    sheet_rows += [("row", by_name[n]) for n in NAMED if n in by_name]
    sheet_rows.append(("head", f"MOBS - gloss only, albedo must be identical "
                               f"({len(MOB_DIRS)} folders, {mobs} textures)"))
    sheet_rows += [("row", by_name[n]) for n in MOBS if n in by_name]

    for palette in ("2", "3", "4", "5", "6", "8"):
        group = [r for r in rows if r["recipe"] == "quantise" and r["palette"] == palette]
        if not group:
            continue
        group.sort(key=lambda r: -float(r["structure"]))
        sheet_rows.append(("head", f"QUANTISE to {palette} colours  ({len(group)} textures)"
                                   f"   - highest structure first"))
        sheet_rows += [("row", r) for r in group[:6]]

    keep = sorted([r for r in rows if r["recipe"] == "keep"], key=lambda r: float(r["d98"]))
    sheet_rows.append(("head", f"KEEP - vanilla texture, plastic material only ({len(keep)})"
                               f"   - closest to the quantise threshold first"))
    sheet_rows += [("row", r) for r in keep[:6]]

    sheet = Image.new("RGBA", (2 * CELL, (len(sheet_rows) + 1) * CELL), (24, 24, 28, 255))
    d = ImageDraw.Draw(sheet)
    d.text((8, 6), "Plasticify scaled quantisation   vanilla | built", fill=(255, 255, 255, 255))
    y = 1
    for kind, payload in sheet_rows:
        if kind == "head":
            d.rectangle([0, y * CELL, 2 * CELL, y * CELL + 22], fill=(40, 40, 52, 255))
            d.text((8, y * CELL + 6), payload, fill=(255, 255, 255, 255))
            y += 1
            continue
        r = payload
        pin = " PINNED" if r["pinned"] else ""
        d.text((6, y * CELL + 4), r["texture"].split("/")[-1][:22], fill=(230, 230, 120, 255))
        d.text((6, y * CELL + CELL - 14),
               f"{r['recipe']} {r['palette'] or '-'}col  str {r['structure']}  "
               f"d98 {r['d98']}{pin}", fill=(180, 220, 255, 255))
        sheet.alpha_composite(tile(first_frame(vanilla(r["texture"]))), (0, y * CELL))
        sheet.alpha_composite(tile(first_frame(built(r["texture"]))), (CELL, y * CELL))
        y += 1
    sheet.convert("RGB").save(OUT, optimize=True)

    print("wrote", OUT, sheet.size)
    for kind, payload in sheet_rows:
        if kind == "head":
            print(f"\n{payload}")
            continue
        r = payload
        print(f"   {r['recipe']:9} {r['palette'] or '-':>2}col  str {r['structure']:>5}  "
              f"d98 {r['d98']:>5}  {r['texture']}{'  [pinned]' if r['pinned'] else ''}")


if __name__ == "__main__":
    main()
