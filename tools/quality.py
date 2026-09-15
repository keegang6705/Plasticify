"""Regression check: did quantisation keep each texture's colour?

For every texture, compare the visible-pixel mean of the vanilla original with
the built albedo. Quantisation should shift that mean only a little - it keeps
local colours and removes the intermediates - so a big shift means a texture
collapsed into something wrong. Textures shifted by more than 30/255 are listed.

    python tools/quality.py
"""
import io
import os
import sys

import numpy as np
from PIL import Image

from common import ROOT, read_vanilla, vanilla_textures

ROOTS = ("block", "entity", "item", "models")
PACK  = os.path.join(ROOT, "assets", "minecraft", "textures")
LIMIT = 30      # a max-channel mean shift above this is worth looking at


def main():
    rels = vanilla_textures(ROOTS)
    deltas, colours, worst = [], [], []
    for rel in rels:
        p = os.path.join(PACK, rel.replace("/", os.sep))
        if not os.path.exists(p):
            continue
        v = np.asarray(Image.open(io.BytesIO(read_vanilla(rel))).convert("RGBA"),
                       dtype=np.float32)
        b = np.asarray(Image.open(p).convert("RGBA"), dtype=np.float32)
        if v.shape != b.shape:
            continue
        vis = v[..., 3] > 8
        if not vis.any():
            continue
        mv, mb = v[..., :3][vis].mean(axis=0), b[..., :3][vis].mean(axis=0)
        d = float(np.abs(mv - mb).max())
        deltas.append((d, rel))
        colours.append(len(np.unique(
            b[..., :3].astype(np.uint8).reshape(-1, 3)[vis.reshape(-1)], axis=0)))
        if d > LIMIT:
            worst.append((d, rel, tuple(int(round(x)) for x in mv),
                          tuple(int(round(x)) for x in mb)))

    if not deltas:
        sys.exit("no built textures found - run tools/build.py first")

    deltas.sort(reverse=True)
    colours = np.array(colours)
    all_d = [d for d, _ in deltas]
    print(f"textures compared          : {len(deltas)}")
    print(f"mean colour shift (max ch) : median {np.median(all_d):5.1f}   "
          f"p90 {np.percentile(all_d, 90):5.1f}   max {deltas[0][0]:5.1f}")
    print(f"textures shifted > {LIMIT:<3}     : {len(worst)}")
    for d, rel, mv, mb in worst[:15]:
        print(f"   {d:5.1f}  {rel:56} {mv} -> {mb}")
    print(f"\npalette size actually used : min {colours.min()}  "
          f"median {int(np.median(colours))}  max {colours.max()}")
    print("largest palette users:")
    for d, rel in sorted(zip(colours, rels), reverse=True)[:5]:
        print(f"   {d:4d}  {rel}")


if __name__ == "__main__":
    main()
