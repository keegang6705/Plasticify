"""Calibrate the tier thresholds against curated expectations.

Tiers, by how much design a texture carries:

  flat      one colour + noise          -> fill with the dominant colour
  detailed  a real design, few levels   -> quantise to crisp flat panels
  keep      rich, high-contrast art     -> keep the vanilla texture, material only

Candidate metrics, all over visible pixels only:

  uni24/32/40   fraction within t/255 of the dominant colour (how much is one colour)
  d50/75/90/98  percentile of the max-channel distance from the dominant colour
                (how much deliberate contrast the design has)
  struct        p90 of |blur(r) - mean| - coherent shape, as opposed to speckle

The last table is the one that matters: it shows how many textures each candidate
threshold pair would route into each tier, which is how `PALETTE_LADDER` and
`T_KEEP` in `build.py` were chosen. Section headings are what a texture *should*
be, so a metric that lands a row in the wrong section is a metric that will
misroute the whole family.

    python tools/calibrate.py
"""
import io

import numpy as np
from PIL import Image, ImageFilter

from common import read_vanilla, vanilla_textures

ROOTS = ("block", "entity", "item", "models")

EXPECT = {
    "flat": [
        "block/stone", "block/dirt", "block/sand", "block/gravel", "block/clay",
        "block/white_wool", "block/red_wool", "block/black_concrete",
        "block/lime_concrete_powder", "block/terracotta", "block/netherrack",
        "block/end_stone", "block/deepslate", "block/tuff", "block/snow",
        "block/iron_block", "block/gold_block", "block/emerald_block",
        "block/redstone_block", "block/coal_block", "block/bedrock", "block/obsidian",
        "block/moss_block", "block/soul_sand", "block/white_concrete",
    ],
    "detailed": [
        "block/oak_log", "block/oak_planks", "block/birch_log", "block/bookshelf",
        "block/crafting_table_front", "block/furnace_side", "block/cobblestone",
        "block/stone_bricks", "block/bricks", "block/copper_grate", "block/ladder",
        "block/rail", "block/barrel_side", "block/lectern_front", "block/loom_front",
        "block/smithing_table_front", "block/cartography_table_side1",
        "block/chiseled_stone_bricks", "block/furnace_front", "block/blast_furnace_front",
        "block/oak_door_bottom", "block/oak_trapdoor", "block/glass_pane_top",
    ],
    "keep": [
        "block/carved_pumpkin", "block/jack_o_lantern", "block/tnt", "block/tnt_side",
        "block/tnt_top", "block/tnt_bottom", "block/cake_top", "block/cake_side",
        "block/enchanting_table_side", "block/enchanting_table_top",
        "block/chiseled_bookshelf_occupied", "block/red_bed_head_up",
        "block/target_side", "block/target_top", "block/jukebox_top",
        "block/furnace_front_on", "block/blast_furnace_front_on",
        "block/crafting_table_top", "block/brewing_stand", "block/beacon",
        "block/conduit", "block/respawn_anchor_side0", "block/note_block",
        "block/dragon_egg", "block/sculk_catalyst_side", "block/creaking_heart",
    ],
}


def load(rel):
    return np.asarray(Image.open(io.BytesIO(read_vanilla(rel + ".png")))
                      .convert("RGBA"), dtype=np.float32)


def prefill(rgb, vis):
    """Invisible pixels take the mean visible colour, so the blur cannot bleed black."""
    if vis.all() or not vis.any():
        return rgb
    out = rgb.copy()
    out[~vis] = rgb[vis].mean(axis=0)
    return out


def metrics(rel):
    """-> (struct, [uni24, uni32, uni40], [d50, d75, d90, d98]) or None if invisible."""
    a = load(rel)
    rgb, alpha = a[..., :3], a[..., 3]
    vis = alpha > 8
    if not vis.any():
        return None
    mean = rgb[vis].mean(axis=0)
    r = max(2, int(round(4 * rgb.shape[1] / 256)))
    blur = np.asarray(Image.fromarray(np.clip(prefill(rgb, vis), 0, 255).astype(np.uint8))
                      .filter(ImageFilter.GaussianBlur(r)), dtype=np.float32)
    struct = float(np.percentile(np.abs(blur - mean).max(axis=2)[vis], 90))

    rgb8 = np.clip(rgb, 0, 255).astype(np.uint8)
    pix = rgb8[vis].reshape(-1, 3)
    q = Image.fromarray(pix.reshape(1, -1, 3)).quantize(
        colors=6, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    pal = np.asarray(q.getpalette()[:18], dtype=np.int32).reshape(-1, 3)
    idx = np.asarray(q).reshape(-1)
    dom = pal[int(np.bincount(idx, minlength=len(pal)).argmax())]
    dist = np.abs(pix.astype(np.int32) - dom).max(axis=1)
    uni = [float((dist <= t).mean()) for t in (24, 32, 40)]
    pct = [float(np.percentile(dist, p)) for p in (50, 75, 90, 98)]
    return struct, uni, pct


def main():
    print(f"{'texture':44} {'struct':>7} {'uni24':>6} {'uni32':>6} {'uni40':>6} "
          f"{'d50':>5} {'d75':>5} {'d90':>5} {'d98':>5}")
    for want, group in EXPECT.items():
        print(f"\n=== expect {want.upper()} ===")
        for rel in group:
            try:
                m = metrics(rel)
            except KeyError:
                print(f"   {rel:41} (not in jar)")
                continue
            if m is None:
                continue
            st, uni, pct = m
            print(f"   {rel:41} {st:7.2f} {uni[0]:6.3f} {uni[1]:6.3f} {uni[2]:6.3f} "
                  f"{pct[0]:5.0f} {pct[1]:5.0f} {pct[2]:5.0f} {pct[3]:5.0f}")

    print("\n=== corpus: how many textures each threshold pair would put in each tier ===")
    rows = []
    for rel in [r[:-4] for r in vanilla_textures(ROOTS)]:
        try:
            m = metrics(rel)
        except Exception:                                           # noqa: BLE001
            continue
        if m:
            rows.append((rel, m[1][1], m[2][3]))        # uni32, d98
    uni = np.array([r[1] for r in rows])
    d98 = np.array([r[2] for r in rows])
    for u_t in (0.80, 0.85, 0.90, 0.95):
        flat = uni >= u_t
        rest = ~flat
        for k_t in (80, 100, 120, 140):
            keep = rest & (d98 >= k_t)
            det = rest & ~keep
            print(f"  uni32>={u_t:.2f}  d98>={k_t:3d}  ->  flat {int(flat.sum()):5d}  "
                  f"quantise {int(det.sum()):5d}  keep {int(keep.sum()):5d}")


if __name__ == "__main__":
    main()
