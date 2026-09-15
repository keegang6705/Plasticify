"""Build the pack.

A standalone pack that overrides every vanilla texture under textures/block,
textures/entity, textures/item and textures/models with a flat plastic albedo
plus LabPBR _n/_s maps, so every block, entity and item in Minecraft renders as
plastic on its own.

The pack root is this repo - the folder holding pack.mcmeta - so a
build lands in the versioned pack itself; `--out DIR` writes a
throwaway build somewhere else instead.

Design notes
------------
* Output keeps the SOURCE resolution and the full frame count, so animated
  textures stay animated and .mcmeta can simply be copied.

* Albedo recipe ("crisp plastic", v4) - the quantisation level SCALES with how
  much shape the texture has, because one flat colour makes a block impossible
  to tell apart from its neighbours:

      shape   palette   examples
      ------------------------------------------------
      < 3      2        stone, wool, concrete, sand
      < 10     3        cobblestone, dirt, resin, prismarine, signs
      < 20     4        planks, stone bricks, grates, polished stone
      < 30     5        note block, furnace side, deepslate bricks
      < 45     6        crafting table, barrel, amethyst
      else     8        everything else
      d98>=110 keep     carved pumpkin, TNT, beds, mob faces, item icons

  Every quantised texture also gets the tolerance filter first: 3x3, tolerance
  28, applied per frame.  The palette is one adaptive median-cut palette for the
  WHOLE atlas, built from visible pixels only, so animation frames never flicker.

* PINS (see PINS): families where the metric lands on the wrong side.  Signs and
  hanging signs are plank boards whose shape comes from the model, so they are
  pinned to 3 colours whatever their texture scores; the prismarine family is
  pinned to 3; every mob (see MOB_DIRS) is pinned to keep, by request, so a face
  keeps its eyes and gets the glossy material without being flattened.

  v1 (the reported bug) blurred the texture and kept 25% of the blur:
      mean + 0.25 * (blur - mean)
  That made highly detailed blocks - chiseled bookshelf, beds, carved pumpkin,
  copper - look like a muddy smear: blur keeps the low frequencies that carry no
  shape and destroys the high frequencies that do.  v2 quantised everything, v3
  added a single-colour flat tier, v4 replaced that tier with the ladder above.

* Only pixels with alpha > 8 are recoloured, so semi-transparent and cut-out
  textures keep their blending.  Invisible pixels are pre-filled with the mean
  visible colour before filtering/quantising, so nothing bleeds a black halo
  into the mipmaps.

* _n is flat (127,127,255,255); _s is the pack's canonical
  (208,20,0,255) = roughness 0.034, F0 7.8%.

Usage
-----
    python tools/build.py            # build into the pack repo
    python tools/build.py --force    # rebuild everything
    python tools/build.py --count    # report what vanilla has
    python tools/build.py --list     # palette/keep split, no build
    python tools/build.py --icon     # redraw pack.png only
    python tools/build.py --out DIR  # build into DIR instead
    python tools/build.py --only chiseled_bookshelf --force
    python tools/build.py --jar JAR  # read vanilla from this client jar
"""
import io, os, re, sys, json, csv, fnmatch, collections
import numpy as np
from PIL import Image, ImageFilter, ImageDraw

from common import ANALYSIS, ROOT, vanilla_textures, vanilla_zip



def _arg_out():
    """--out DIR writes the pack somewhere other than this repo."""
    for i, a in enumerate(sys.argv):
        if a == "--out":
            if i + 1 >= len(sys.argv):
                sys.exit("--out needs a directory")
            return os.path.abspath(sys.argv[i + 1])
        if a.startswith("--out="):
            return os.path.abspath(a.split("=", 1)[1])
    return None


OUT  = _arg_out() or ROOT
AS   = os.path.join(OUT, "assets", "minecraft")
Z       = vanilla_zip()                 # the client jar; see common.py
_jarset = set(Z.namelist())

ROOTS   = ["block", "entity", "item", "models"]
MAXSIZE = 256       # downscale anything larger
MIN_COL = 6         # palette floor (small pixel-art textures)
MAX_COL = 12        # palette ceiling (big skins / gradient textures)
SIGMA_T = 28        # colour tolerance of the flattening filter
SIGMA_R = 1         # ... and its radius (1 = 3x3; 2 merges small details)
# Quantisation ladder: (structure limit, palette size).  Scaled detail rather
# than one flat colour, so a block is still identifiable by its silhouette and
# shading - a single colour made stone, cobblestone and sandstone the same grey.
PALETTE_LADDER = [(3, 2), (10, 3), (20, 4), (30, 5), (45, 6)]
PALETTE_TOP    = 8
T_KEEP   = 110      # >= this design contrast -> leave the vanilla texture alone
# Pins: families where the metric lands on the wrong side.  Value is a palette
# size, or None to keep the vanilla texture untouched.
#   signs / hanging signs: plank boards whose SHAPE comes from the model, so they
#     should be as flat as planks whatever their texture scores (their d98 runs
#     30-213 across wood types, which otherwise splits the family three ways).
#   prismarine family: plain stone-like material, scored 22 (mid-ladder) only
#     because of its speckle.
#   every mob: a mob texture is a drawing - eyes, snout, fur markings - and
#     quantising it at 2-6 colours erases exactly those details.  Mobs are
#     therefore pinned to keep, which still ships the flat _s/_n material, so
#     they read as glossy plastic without their albedo being touched.  This is
#     every LIVING entity; block-like entity textures (chests, banners, shields,
#     boats, beds, decorated pots, projectiles, armour) stay on the ladder.
MOB_DIRS = [
    "allay", "armadillo", "armorstand", "axolotl", "bat", "bear", "bee", "blaze",
    "breeze", "camel", "cat", "chicken", "copper_golem", "cow", "creaking",
    "creeper", "dolphin", "enderdragon", "enderman", "endermite", "fish", "fox",
    "frog", "ghast", "goat", "guardian", "hoglin", "horse", "illager",
    "iron_golem", "llama", "panda", "parrot", "phantom", "pig", "piglin",
    "player", "rabbit", "sheep", "shulker", "silverfish", "skeleton", "slime",
    "sniffer", "snow_golem", "spider", "squid", "strider", "sulfur_cube",
    "tadpole", "turtle", "villager", "wandering_trader", "warden", "witch",
    "wither", "wolf", "zombie", "zombie_villager",
]
PINS = [
    # boards whose SHAPE comes from the model, so the texture should be as flat
    # as a plank whatever it scores
    ("block/*_sign*", 3),
    ("item/*_sign*", 3),
    ("block/*_door_*", 4),
    ("item/*_door*", 4),
    ("block/*_trapdoor", 4),
    ("item/*trapdoor*", 4),
    ("block/*_shelf", 4),
    ("block/*_bars", 4),
    ("item/*_bars", 4),
    ("block/*_chain", 3),
    ("item/*_chain", 3),
    # plain materials that the contrast test misroutes into keep
    ("block/prismarine*", 3),
    ("block/*_ore", 4),
    ("block/diorite", 3),
    ("block/amethyst_block", 3),
    ("block/budding_amethyst", 3),
    ("block/redstone_block", 3),
    ("block/magma", 3),
    ("block/ancient_debris_top", 3),
    ("block/melon_side", 3),
    ("block/honeycomb_block", 3),
    ("block/cactus_side", 3),
] + [(f"entity/{d}/*", None) for d in MOB_DIRS]
S_FLAT  = (208, 20, 0, 255)
N_FLAT  = (127, 127, 255, 255)
AUTHOR  = "keegang6705"
SITE    = "https://keegang.cc/"
VERSION = "1.0"
CREDIT  = "DeepseekV4"

COUNT_ONLY = "--count" in sys.argv
FORCE      = "--force" in sys.argv
ONLY       = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
LIST_ONLY  = "--list" in sys.argv
ICON_ONLY  = "--icon" in sys.argv



def van_entries():
    """every vanilla texture under the included roots"""
    return vanilla_textures(ROOTS)


def palette_size(w, h):
    """bigger textures carry more real shading, so they get more colours"""
    return int(max(MIN_COL, min(MAX_COL, round((w * h) ** 0.5 / 2.7))))


def _prefill(rgb, vis):
    """give invisible pixels the mean visible colour so filters do not bleed black"""
    if vis.all() or not vis.any():
        return rgb
    out = rgb.copy()
    out[~vis] = rgb[vis].mean(axis=0)
    return out


def dominant_colour(arr, colors=MIN_COL):
    """-> (dominant RGB, visible pixels as Nx3 uint8, palette). None if invisible.

    The dominant palette entry is used rather than the mean so a handful of
    stray dark pixels cannot drag a whole block off-colour.
    """
    vis = arr[..., 3] > 8
    if not vis.any():
        return None, None, None
    rgb8 = np.clip(arr[..., :3], 0, 255).astype(np.uint8)
    pix = rgb8[vis].reshape(-1, 3)
    q = Image.fromarray(pix.reshape(1, -1, 3)).quantize(
        colors=colors, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    pal = np.asarray(q.getpalette()[:colors * 3], dtype=np.int32).reshape(-1, 3)
    counts = np.bincount(np.asarray(q).reshape(-1), minlength=len(pal))
    return pal[int(counts.argmax())], pix, pal


def tier_metrics(arr):
    """The two numbers the tier decision uses.

    uni : share of visible pixels within 32/255 of the dominant colour
          (how much of the face is one colour)
    d98 : p98 of the distance from that colour
          (how much deliberate contrast the design has)
    """
    dom, pix, _ = dominant_colour(arr)
    if dom is None:
        return 1.0, 0.0
    dist = np.abs(pix.astype(np.int32) - dom).max(axis=1)
    return float((dist <= 32).mean()), float(np.percentile(dist, 98))


def structure(arr):
    """How much large-scale SHAPE the texture has, ignoring per-pixel speckle.

    p90 of the blurred deviation from the mean colour.  This is the signal that
    separates noise from design in the FLAT test: dirt's speckle scores ~4, but
    the holes in a copper grate score ~19, and only the latter is a feature
    worth keeping.
    """
    rgb, a = arr[..., :3], arr[..., 3]
    vis = a > 8
    if not vis.any():
        return 0.0
    mean = rgb[vis].mean(axis=0)
    r = max(2, int(round(4 * rgb.shape[1] / 256)))
    blur = np.asarray(
        Image.fromarray(np.clip(_prefill(rgb, vis), 0, 255).astype(np.uint8))
        .filter(ImageFilter.GaussianBlur(r)), dtype=np.float32)
    return float(np.percentile(np.abs(blur - mean).max(axis=2)[vis], 90))


def palette_for(s):
    """palette size for a texture with shape score s (see PALETTE_LADDER)"""
    for limit, n in PALETTE_LADDER:
        if s < limit:
            return n
    return PALETTE_TOP


def pinned(rel):
    """-> (is_pinned, palette size or None for keep). rel carries the .png"""
    stem = rel[:-4] if rel.endswith(".png") else rel
    for pat, val in PINS:
        if fnmatch.fnmatch(stem, pat):
            return True, val
    return False, None


def recipe_of(rel, arr):
    """-> ("keep", None) | ("quantise", palette_size)

    Quantisation level scales with the texture's shape score, so plain blocks
    still read as themselves: stone gets 2 tones, cobblestone 3, planks 4.
    A texture with strong contrast (d98) is left alone whatever its shape,
    which is what protects the drawings - pumpkin's face, TNT's letters, target
    rings, item icons - and mob faces.
    """
    hit, val = pinned(rel)
    if hit:
        return ("keep", None) if val is None else ("quantise", val)
    _, d98 = tier_metrics(arr)
    if d98 >= T_KEEP:
        return ("keep", None)
    return ("quantise", palette_for(structure(arr)))


def flat_fill(arr):
    """Unused since v4 (the ladder replaced the single-colour tier) - kept
    because it is the clearest statement of what v3 did, and the fastest way to
    see what one colour per block looks like."""
    out = arr.copy()
    vis = arr[..., 3] > 8
    if not vis.any():
        return out
    mean = arr[..., :3][vis].mean(axis=0).astype(np.float32)
    out[..., :3] = np.where(vis[..., None], mean, out[..., :3])
    return out


def fill_hex(arr):
    vis = arr[..., 3] > 8
    if not vis.any():
        return "-"
    mean = arr[..., :3][vis].mean(axis=0)
    return "#%02X%02X%02X" % tuple(int(round(x)) for x in mean)


def denoise(arr):
    """Tolerance ('sigma') flattening filter.

    Each pixel is averaged with the neighbours whose colour is within SIGMA_T of
    it.  Speckle inside a region averages out because those neighbours are close
    in colour; thin 1 px lines and hard edges survive because the neighbours on
    the other side of the edge are rejected.  A median filter looks equivalent
    at a glance but eats 1 px lines - it wiped the rings off the target block.
    """
    rgb, a = arr[..., :3], arr[..., 3]
    vis = a > 8
    if not vis.any():
        return arr
    h, w = rgb.shape[:2]
    src = _prefill(rgb, vis)
    pad = np.pad(src, ((SIGMA_R, SIGMA_R), (SIGMA_R, SIGMA_R), (0, 0)), mode="edge")
    acc = np.zeros_like(src)
    cnt = np.zeros((h, w), dtype=np.float32)
    for dy in range(-SIGMA_R, SIGMA_R + 1):
        for dx in range(-SIGMA_R, SIGMA_R + 1):
            nb = pad[SIGMA_R + dy:SIGMA_R + dy + h, SIGMA_R + dx:SIGMA_R + dx + w]
            m = np.abs(nb - src).max(axis=2) <= SIGMA_T
            acc += np.where(m[..., None], nb, 0.0)
            cnt += m
    out = arr.copy()
    out[..., :3] = np.where(vis[..., None], acc / np.maximum(cnt, 1)[..., None], rgb)
    return out


def quantise(arr, colors):
    """adaptive-palette flat fill of the whole atlas; alpha is preserved exactly.

    The palette is built from the VISIBLE pixels only.  Building it from the
    whole canvas (what Image.quantize does) makes alpha padding - leaves,
    flowers, cut-out items - eat palette entries, which rounds the real colours
    away.
    """
    rgb8 = np.clip(arr[..., :3], 0, 255).astype(np.uint8)
    a = arr[..., 3:]
    vis = arr[..., 3] > 8
    if not vis.any():
        return arr
    key = (rgb8[..., 0].astype(np.uint32) << 16) | \
          (rgb8[..., 1].astype(np.uint32) << 8) | rgb8[..., 2].astype(np.uint32)
    if np.unique(key).size <= colors:
        return arr                      # already flat enough - leave it alone

    strip = rgb8[vis].reshape(1, -1, 3)
    pal = Image.fromarray(strip).quantize(
        colors=colors, method=Image.MEDIANCUT,
        dither=Image.Dither.NONE).getpalette()[:colors * 3]
    pal = np.asarray(pal, dtype=np.int32).reshape(-1, 3)

    # int32, not int16: a single channel distance is 255^2 = 65025, which
    # overflows int16 and silently picks the wrong nearest colour.
    flat = rgb8.reshape(-1, 3).astype(np.int32)
    out = np.empty_like(flat)
    step = 1 << 16
    for i in range(0, len(flat), step):
        chunk = flat[i:i + step]
        d = ((chunk[:, None, :] - pal[None, :, :]) ** 2).sum(axis=2)
        out[i:i + step] = pal[d.argmin(axis=1)]
    return np.concatenate([out.reshape(rgb8.shape).astype(np.float32), a], axis=2)


def split_frames(a, animated):
    """Split into animation frames ONLY when vanilla ships a .mcmeta for it.

    Aspect ratio is not a safe test: entity textures like polarbear.png are
    128x64, which is not an animation. Cropping those to square would break
    their UV mapping.
    """
    h, w = a.shape[:2]
    if animated and w > 0 and h % w == 0 and h >= w:
        n = h // w
        return [a[i * w:(i + 1) * w] for i in range(n)], True
    return [a], False


def fit_frame(f, is_anim_frame):
    """downscale to MAXSIZE preserving aspect; animation frames stay square"""
    h, w = f.shape[:2]
    if is_anim_frame:
        if w <= MAXSIZE:
            return f
        return np.asarray(
            Image.fromarray(np.clip(f, 0, 255).astype(np.uint8))
            .resize((MAXSIZE, MAXSIZE), Image.LANCZOS), dtype=np.float32)
    if max(h, w) <= MAXSIZE:
        return f
    scale = MAXSIZE / max(h, w)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    return np.asarray(
        Image.fromarray(np.clip(f, 0, 255).astype(np.uint8))
        .resize((nw, nh), Image.LANCZOS), dtype=np.float32)


def make_icon(path, size=128, ss=4):
    """The pack icon: a pink plastic toy brick.

    Isometric block, four studs on top, one hard specular streak - "plastic"
    rather than "a pink button".  Drawn at ss x size and downscaled, because
    diagonals drawn straight at 128 px come out stepped and read as dirt once
    the pack list shrinks the icon.
    """
    N = size * ss
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    LINE, RIM = (104, 26, 66, 255), (255, 216, 240, 255)
    hi = max(1, round(N * 0.008))          # outline weight, 1 px at 128

    cx, s, body, top_y = N / 2.0, N * 0.30, N * 0.28, N * 0.215
    o = (cx, top_y)
    u, v, dn = (s, s * 0.5), (-s, s * 0.5), (0.0, body)

    def P(*pts):
        return [(round(x), round(y)) for x, y in pts]

    def add(p, q, k=1.0):
        return (p[0] + q[0] * k, p[1] + q[1] * k)

    back = o
    right, front, left = add(o, u), add(add(o, u), v), add(o, v)
    top = [back, right, front, left]
    rface = [right, front, add(front, dn), add(right, dn)]
    lface = [left, front, add(front, dn), add(left, dn)]

    def clip(poly):
        m = Image.new("L", (N, N), 0)
        ImageDraw.Draw(m).polygon(P(*poly), fill=255)
        return m

    def shade(poly, c0, c1):
        """fill a face with a top-to-bottom gradient - an evenly lit plastic
        face looks like paper; the ramp is what makes it look moulded"""
        m = clip(poly)
        x0, y0, x1, y1 = m.getbbox()
        t = np.linspace(0, 1, max(2, y1 - y0), dtype=np.float32)[:, None]
        ramp = (np.array(c0, np.float32)[None, :] * (1 - t)
                + np.array(c1, np.float32)[None, :] * t)
        layer = np.zeros((N, N, 4), np.float32)
        layer[y0:y1] = np.repeat(ramp[:, None, :], N, axis=1)
        g = Image.fromarray(np.clip(layer, 0, 255).astype(np.uint8))
        g.putalpha(m)
        img.alpha_composite(g)

    shade(lface, (176, 56, 118, 255), (150, 42, 100, 255))
    shade(rface, (228, 92, 160, 255), (202, 72, 138, 255))
    shade(top, (255, 168, 216, 255), (249, 136, 194, 255))

    # gloss across the top face, drawn UNDER the studs because they stand proud
    sheen = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).polygon(
        P(add(add(o, u, -0.05), v, 0.40), add(add(o, u, 1.05), v, 0.40),
          add(add(o, u, 1.05), v, 0.62), add(add(o, u, -0.05), v, 0.62)),
        fill=(255, 255, 255, 120))
    img.alpha_composite(Image.composite(
        sheen.filter(ImageFilter.GaussianBlur(N * 0.012)),
        Image.new("RGBA", (N, N), (0, 0, 0, 0)), clip(top)))

    # studs: 2 x 2 across the top face, back row first.  The body is shaded in
    # two halves so it reads as a cylinder, and the cap is a step lighter than
    # the face - that step is what makes them look raised rather than drawn on.
    rs, hs = s * 0.185, s * 0.14
    for a, b in ((0.30, 0.30), (0.70, 0.30), (0.30, 0.70), (0.70, 0.70)):
        c = add(add(o, u, a), v, b)
        cap = (c[0], c[1] - hs)
        d.ellipse(P((c[0] - rs * 1.12, c[1] - rs * 0.72),
                    (c[0] + rs * 1.12, c[1] + rs * 0.72)), fill=(234, 118, 176, 255))
        d.polygon(P((c[0] - rs, c[1]), (c[0] + rs, c[1]),
                    (cap[0] + rs, cap[1]), (cap[0] - rs, cap[1])), fill=(228, 108, 166, 255))
        d.polygon(P((c[0], c[1]), (c[0] + rs, c[1]),
                    (cap[0] + rs, cap[1]), (cap[0], cap[1])), fill=(247, 140, 198, 255))
        for sx in (-1, 1):
            d.line(P((c[0] + sx * rs, c[1]), (cap[0] + sx * rs, cap[1])),
                   fill=LINE, width=hi)
        d.ellipse(P((cap[0] - rs, cap[1] - rs * 0.58),
                    (cap[0] + rs, cap[1] + rs * 0.58)), fill=(255, 172, 220, 255),
                  outline=LINE, width=hi)
        d.arc(P((cap[0] - rs * 0.62, cap[1] - rs * 0.40),
                (cap[0] + rs * 0.62, cap[1] + rs * 0.40)), 200, 340,
              fill=(255, 235, 250, 255), width=hi)

    # a hard glint on the right face, the edge light, then the outline
    glint = add(add(right, dn, 0.28), (u[0] * -0.5, u[1] * -0.5), 1.0)
    d.line(P(add(glint, (0, -s * 0.15)), add(glint, (0, s * 0.15))),
           fill=(255, 216, 238, 185), width=max(hi, round(N * 0.011)))
    d.line(P(left, back, right), fill=RIM, width=hi, joint="curve")
    d.line(P(back, right, add(right, dn), add(front, dn), add(left, dn), left, back),
           fill=LINE, width=max(2, round(N * 0.012)), joint="curve")

    img.resize((size, size), Image.LANCZOS).save(path, optimize=True)


def build_one(rel):
    """vanilla texture -> plastic albedo array. Returns (array, animated, frames)"""
    raw = Z.read("assets/minecraft/textures/" + rel)
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    a = np.asarray(im, dtype=np.float32)
    animated = ("assets/minecraft/textures/" + rel + ".mcmeta") in _jarset
    frames, is_anim = split_frames(a, animated)
    frames = [fit_frame(f, is_anim) for f in frames]
    if not frames:
        return None
    n = len(frames)
    fh, fw = frames[0].shape[:2]
    atlas = np.empty((n * fh, fw, 4), dtype=np.float32)
    for i, f in enumerate(frames):
        atlas[i * fh:(i + 1) * fh] = f

    recipe, n_col = recipe_of(rel, atlas)
    if recipe == "keep":                        # too much art to touch: vanilla pixels
        return {"recipe": recipe, "palette": None, "animated": animated, "frames": n,
                "h": a.shape[0], "w": a.shape[1], "raw": raw}
    out = quantise(denoise_per_frame(frames), n_col)
    return {"recipe": recipe, "palette": n_col, "animated": animated, "frames": n,
            "h": out.shape[0], "w": out.shape[1],
            "array": np.clip(out, 0, 255).astype(np.uint8)}


def denoise_per_frame(frames):
    """tolerance filter each frame separately, then stack back into one atlas"""
    done = [denoise(f) for f in frames]
    n, fh, fw = len(done), done[0].shape[0], done[0].shape[1]
    atlas = np.empty((n * fh, fw, 4), dtype=np.float32)
    for i, f in enumerate(done):
        atlas[i * fh:(i + 1) * fh] = f
    return atlas


def write_list(entries):
    """The palette ladder, as a list to review: csv + markdown."""
    rows = []
    for rel in entries:
        try:
            a = np.asarray(Image.open(io.BytesIO(
                Z.read("assets/minecraft/textures/" + rel))).convert("RGBA"), dtype=np.float32)
        except Exception as exc:                                    # noqa: BLE001
            print(f"   !! {rel}: {exc!r}")
            continue
        uni, d98 = tier_metrics(a)
        st = structure(a)
        recipe, n_col = recipe_of(rel, a)
        hit, _ = pinned(rel)
        rows.append((rel, uni, d98, st, recipe, n_col, fill_hex(a), hit))
    rows.sort(key=lambda r: (r[3], -r[2]))

    csv_path = os.path.join(ANALYSIS, "recipe_split.csv")
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with io.open(csv_path, "w", encoding="utf-8", newline="\n") as fh:
        w = csv.writer(fh)
        w.writerow(["texture", "uni32", "d98", "structure", "recipe", "palette",
                    "pinned", "mean_colour"])
        for rel, uni, d98, st, recipe, n_col, hexc, hit in rows:
            w.writerow([rel, f"{uni:.3f}", f"{d98:.1f}", f"{st:.2f}", recipe,
                        "" if n_col is None else n_col, "yes" if hit else "", hexc])

    md_path = os.path.join(ANALYSIS, "recipe_split.md")
    counts = collections.Counter((r[4], r[5]) for r in rows)
    ladder = {n: [r for r in rows if r[4] == "quantise" and r[5] == n] for _, n in PALETTE_LADDER}
    ladder[PALETTE_TOP] = [r for r in rows if r[4] == "quantise" and r[5] == PALETTE_TOP]
    keep = [r for r in rows if r[4] == "keep"]
    with io.open(md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Plasticify recipe split\n\n")
        fh.write("Every vanilla texture is measured, then quantised to a palette "
                 "sized by how much shape it has - scaled, because a single flat "
                 "colour makes a block impossible to tell from its neighbours.\n\n")
        fh.write("| measurement | meaning |\n|---|---|\n")
        fh.write("| `structure` | p90 of the blurred deviation from the mean - "
                 "coherent shape, as opposed to per-pixel speckle |\n")
        fh.write("| `d98` | p98 of the distance from the dominant colour - how much "
                 "deliberate contrast the design has |\n")
        fh.write("| `uni32` | share of visible pixels within 32/255 of the dominant "
                 "colour (reported for information) |\n\n")
        fh.write("| rule | palette | textures |\n|---|---|---|\n")
        for limit, n in PALETTE_LADDER:
            fh.write(f"| `structure < {limit}` | {n} colours | {len(ladder[n])} |\n")
        fh.write(f"| otherwise | {PALETTE_TOP} colours | {len(ladder[PALETTE_TOP])} |\n")
        fh.write(f"| `d98 >= {T_KEEP}` | **keep the vanilla texture** | {len(keep)} |\n")
        fh.write(f"| | **total** | {len(rows)} |\n\n")
        fh.write("Pinned families (see `PINS` in the builder):\n\n")
        fh.write("| pattern | recipe | textures |\n|---|---|---|\n")
        mob_pats = {f"entity/{d}/*" for d in MOB_DIRS}
        mob_rows = [r for r in rows if r[0].startswith("entity/")
                    and r[0].split("/")[1] in MOB_DIRS]
        for pat, val in PINS:
            if pat in mob_pats:
                continue
            name = "keep" if val is None else f"quantise, {val} colours"
            cnt = sum(1 for r in rows if fnmatch.fnmatch(
                r[0][:-4] if r[0].endswith(".png") else r[0], pat))
            fh.write(f"| `{pat}` | {name} | {cnt} |\n")
        fh.write(f"| `entity/<mob>/*` ({len(MOB_DIRS)} mob folders) | keep - vanilla "
                 f"texture, plastic material | {len(mob_rows)} |\n")
        for n in [x[1] for x in PALETTE_LADDER] + [PALETTE_TOP]:
            group = ladder[n]
            fh.write(f"\n## Quantise to {n} colours ({len(group)})\n\n")
            fh.write("| texture | structure | d98 | palette | mean colour |\n|---|---|---|---|---|\n")
            for rel, uni, d98, st, _, n_col, hexc, hit in group:
                pin = " *(pinned)*" if hit else ""
                fh.write(f"| `{rel}`{pin} | {st:.1f} | {d98:.0f} | {n_col} | {hexc} |\n")
        fh.write(f"\n## Keep - vanilla texture, plastic material only ({len(keep)})\n\n")
        fh.write("| texture | structure | d98 | mean colour |\n|---|---|---|---|\n")
        for rel, uni, d98, st, _, _, hexc, hit in keep:
            pin = " *(pinned)*" if hit else ""
            fh.write(f"| `{rel}`{pin} | {st:.1f} | {d98:.0f} | {hexc} |\n")
    print("recipe split:")
    for n in [x[1] for x in PALETTE_LADDER] + [PALETTE_TOP]:
        print(f"   quantise {n:2d} colours {len(ladder[n]):5d}")
    print(f"   keep                 {len(keep):5d}")
    print(f"   {'total':20} {len(rows):5d}")
    print(f"\nwrote {csv_path}")
    print(f"wrote {md_path}")
    return rows


def main():
    if ICON_ONLY:
        os.makedirs(OUT, exist_ok=True)
        make_icon(os.path.join(OUT, "pack.png"))
        print("wrote " + os.path.join(OUT, "pack.png"))
        return
    entries = van_entries()
    if ONLY:
        entries = [e for e in entries if ONLY in e]
    if COUNT_ONLY:
        by_root = collections.Counter(e.split("/", 1)[0] for e in entries)
        print(f"vanilla textures to override: {len(entries)}")
        for k, v in by_root.most_common():
            print(f"   {k:10} {v}")
        return
    if LIST_ONLY:
        write_list(entries)
        return

    os.makedirs(AS, exist_ok=True)
    stats = collections.Counter()
    for rel in entries:
        dst = os.path.join(AS, "textures", rel.replace("/", os.sep))
        if os.path.exists(dst) and not FORCE:
            stats["exists"] += 1
            continue
        try:
            built = build_one(rel)
        except KeyError:
            stats["missing in jar"] += 1
            continue
        except Exception as exc:                                    # noqa: BLE001
            stats["failed"] += 1
            print(f"   !! {rel}: {exc!r}")
            continue
        if built is None:
            stats["empty"] += 1
            continue
        stats["recipe " + built["recipe"]] += 1

        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if "raw" in built:                      # keep tier: vanilla bytes, untouched
            io.open(dst, "wb").write(built["raw"])
        else:
            Image.fromarray(built["array"]).save(dst, optimize=True)
        stats["albedo"] += 1
        if built["frames"] > 1:
            stats["animated"] += 1

        # flat LabPBR maps, same dimensions
        h, w = built["h"], built["w"]
        nrm = np.empty((h, w, 4), dtype=np.uint8)
        nrm[..., :] = N_FLAT
        spec = np.empty((h, w, 4), dtype=np.uint8)
        spec[..., :] = S_FLAT
        base = dst[:-4]
        Image.fromarray(nrm).save(base + "_n.png", optimize=True)
        Image.fromarray(spec).save(base + "_s.png", optimize=True)
        stats["pbr pairs"] += 1

        # copy vanilla .mcmeta onto all three
        try:
            meta = Z.read("assets/minecraft/textures/" + rel + ".mcmeta")
        except KeyError:
            meta = None
        if meta is not None:
            for suf in ("", "_n", "_s"):
                io.open(base + suf + ".png.mcmeta", "wb").write(meta)
            stats["mcmeta"] += 1

    print("generated:")
    for k, v in stats.most_common():
        print(f"   {k:18} {v}")

    # metadata
    desc = f"\u00a7bPlasticify {VERSION}\u00a78| \u00a77by \u00a7b{AUTHOR}"
    mcmeta = {
        "pack": {
            "description": desc,
            "pack_format": 88,
            "min_format": [88, 0],
            "max_format": [88, 0],
        }
    }
    io.open(os.path.join(OUT, "pack.mcmeta"), "w", encoding="utf-8", newline="\n").write(
        json.dumps(mcmeta, indent=2, ensure_ascii=False) + "\n")
    # The icon is authored, not generated: the shipped pack.png is a 512 px
    # drawing that make_icon() (128 px) does not reproduce, so a build never
    # overwrites it - `--icon` is the explicit redraw.
    icon = os.path.join(OUT, "pack.png")
    if not os.path.exists(icon):
        make_icon(icon)
    io.open(os.path.join(OUT, "README.md"), "w", encoding="utf-8", newline="\n").write(f"""# Plasticify

**Author:** {AUTHOR} - {SITE} , {CREDIT}

Gives Minecraft a flat, glossy plastic finish.

## What it does

* Blocks and items are replaced with flat plastic versions of themselves, so
  everything in the world looks moulded rather than textured.
* Anything with real artwork in it - pumpkin faces, TNT, item icons, painted
  blocks - keeps its detail and only picks up the plastic shine.
* Mobs are left as they are, shine included, so faces and fur still read
  properly.
* Animations keep animating, at the same speed as vanilla.
* Material maps are included, so shaders light the surface as smooth, glossy
  plastic.

## Install

1. Copy the `Plasticify` folder into your `resourcepacks` folder.
2. In game, open Options -> Resource Packs and enable Plasticify.
3. Put it above any other pack whose textures you want it to replace.

## Requires

The gloss needs a shader with Advanced Materials enabled 
(Shader Options -> Material -> Advanced Materials) with a plain shader or
no shader, it still renders as flat plastic.

Material maps: `_n` is a flat normal, `_s` is roughness 0.03 with 7.8%
reflectivity.

## Left alone

Menus, fonts, maps, paintings, the sky and the colourmaps are not touched, so
nothing becomes hard to read.
""")


if __name__ == "__main__":
    main()
