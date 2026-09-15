"""The gate: does the built pack actually cover vanilla, and is it still plastic?

Checks, in order:

* every vanilla texture in scope has an albedo, a `_n` and an `_s`
* every built image decodes, and is the same size as its vanilla original
* mobs are gloss-only: albedo byte-identical to vanilla, material still flat
  plastic (this is the rule that keeps faces and fur readable)
* `pack.mcmeta` parses, and the pack ships the files it should
* a sample of albedos really is flat

Exit status is 0 even when it finds problems - it is a report, not a gate - but
`violations` near the top of the output is the number to read.
"""
import io
import json
import os
import random

import numpy as np
from PIL import Image

from build import MOB_DIRS, N_FLAT, S_FLAT
from common import ROOT, read_vanilla, vanilla_textures

ROOTS = ("block", "entity", "item", "models")
TEX   = os.path.join(ROOT, "assets", "minecraft", "textures")


def main():
    van = vanilla_textures(ROOTS)
    miss_a, miss_n, miss_s, bad = [], [], [], []
    for rel in van:
        p = os.path.join(TEX, rel.replace("/", os.sep))
        if not os.path.exists(p):
            miss_a.append(rel)
            continue
        if not os.path.exists(p[:-4] + "_n.png"):
            miss_n.append(rel)
        if not os.path.exists(p[:-4] + "_s.png"):
            miss_s.append(rel)
        try:
            Image.open(p).convert("RGBA")
        except Exception as exc:                                    # noqa: BLE001
            bad.append((rel, str(exc)))

    print(f"vanilla textures in scope : {len(van)}")
    print(f"missing albedo            : {len(miss_a)}")
    print(f"missing _n                : {len(miss_n)}")
    print(f"missing _s                : {len(miss_s)}")
    print(f"unreadable                : {len(bad)}")
    for rel in miss_a[:10]:
        print("   albedo  " + rel)
    for rel in miss_n[:10]:
        print("   _n      " + rel)

    # same dimensions as vanilla, so models and animation frames line up
    size_mismatch = []
    for rel in van:
        p = os.path.join(TEX, rel.replace("/", os.sep))
        if not os.path.exists(p):
            continue
        try:
            ours = Image.open(p).size
            theirs = Image.open(io.BytesIO(read_vanilla(rel))).size
        except Exception:                                           # noqa: BLE001
            continue
        if ours != theirs:
            size_mismatch.append((rel, theirs, ours))
    print(f"\nsize differs from vanilla : {len(size_mismatch)}")
    for rel, theirs, ours in size_mismatch[:8]:
        print(f"   {rel}: vanilla {theirs} -> ours {ours}")

    # mobs: vanilla pixels, plastic material - the gloss-only rule
    mob = [r for r in van if r.split("/", 1)[0] == "entity"
           and r.split("/")[1] in MOB_DIRS]
    touched, no_pbr, bad_mat = [], [], []
    for rel in mob:
        p = os.path.join(TEX, rel.replace("/", os.sep))
        if not os.path.exists(p):
            touched.append(rel + " (missing)")
            continue
        if io.open(p, "rb").read() != read_vanilla(rel):
            touched.append(rel)
        for suf, want in (("_n", N_FLAT), ("_s", S_FLAT)):
            q = p[:-4] + suf + ".png"
            if not os.path.exists(q):
                no_pbr.append(rel + suf)
                continue
            m = np.asarray(Image.open(q).convert("RGBA"))
            if m.shape[0] != 0 and not (m.reshape(-1, 4) == np.array(want, np.uint8)).all():
                bad_mat.append(rel + suf)
    print(f"\nmob folders pinned        : {len(MOB_DIRS)}  ({len(mob)} textures)")
    print(f"mob albedo != vanilla     : {len(touched)}")
    for rel in touched[:8]:
        print("   " + rel)
    print(f"mob missing _n/_s         : {len(no_pbr)}")
    print(f"mob _n/_s not flat plastic: {len(bad_mat)}")
    for rel in bad_mat[:8]:
        print("   " + rel)

    print(f"\nviolations                : "
          f"{len(miss_a) + len(miss_n) + len(miss_s) + len(bad) + len(size_mismatch) + len(touched) + len(no_pbr) + len(bad_mat)}")

    # the shipped pack only: assets/ plus the three root files
    shipped = [os.path.join(dp, f)
               for dp, _, fs in os.walk(os.path.join(ROOT, "assets")) for f in fs]
    shipped += [os.path.join(ROOT, n) for n in ("pack.mcmeta", "pack.png", "README.md")
                if os.path.exists(os.path.join(ROOT, n))]
    total = sum(os.path.getsize(f) for f in shipped)
    print(f"\npack files: {len(shipped)}   size: {total / 1048576:.2f} MiB")

    mc = json.loads(io.open(os.path.join(ROOT, "pack.mcmeta"), encoding="utf-8").read())
    print(f"\npack.mcmeta pack keys: {sorted(mc['pack'].keys())}")
    print(f"description: {mc['pack']['description']}")
    for name in ("pack.png", "README.md"):
        print(f"{name} present: {os.path.exists(os.path.join(ROOT, name))}")

    # albedo statistics: is it actually flat plastic?
    random.seed(1)
    present = [r for r in van if os.path.exists(os.path.join(TEX, r.replace("/", os.sep)))]
    print("\nsample albedos (mean colour, luminance std -- low = flat):")
    for rel in random.sample(present, min(12, len(present))):
        a = np.asarray(Image.open(os.path.join(TEX, rel.replace("/", os.sep)))
                       .convert("RGBA"), dtype=np.float32)
        vis = a[..., 3] > 8
        if not vis.any():
            print(f"   {rel:52} fully transparent")
            continue
        mean = a[..., :3][vis].mean(axis=0)
        lum = a[..., :3].mean(axis=2)[vis]
        print(f"   {rel:52} mean={tuple(int(round(x)) for x in mean)} std={lum.std():6.2f}")

    s = np.asarray(Image.open(os.path.join(TEX, "block", "stone_s.png")).convert("RGBA"))
    print(f"\n_s sample modes (stone): R{np.unique(s[..., 0])} G{np.unique(s[..., 1])} "
          f"B{np.unique(s[..., 2])} A{np.unique(s[..., 3])}")


if __name__ == "__main__":
    main()
