"""Pack a Plasticify release.

Zips the shipped pack - `pack.mcmeta`, `pack.png`, `README.md` and `assets/` -
into `dist/Plasticify-<version>.zip`. The version comes out of the pack
description (`VERSION` in `build.py` writes it there), so a release
cannot be named differently from the pack it holds.

Only that whitelist is packed: the tooling in `tools/`, `_analysis/`, `dist/`,
`.git` and any stray archive can never leak into a release. The pack itself is
validated first (metadata parses, `assets/` is populated, nothing required is
missing), and the finished zip is reopened and checked - a resource pack whose
`pack.mcmeta` is not at the root loads as an empty pack, so that is a hard error.

The archive is written with a fixed timestamp and a sorted file order, so the
same pack always produces the same zip.

    python tools/release.py                 # dist/Plasticify-1.0.zip
    python tools/release.py --version 1.1   # override the version
    python tools/release.py --check         # validate and report, write nothing
    python tools/release.py --list          # what would be packed, per folder
    python tools/release.py --out DIR       # write the zip somewhere else

Run `verify.py` for the content gate (coverage, PBR maps, mob
gloss-only); this script only guards the shape of the archive.
"""
import os
import io
import re
import sys
import json
import zipfile

# This script lives in <pack root>/tools, so the pack root - the folder holding
# pack.mcmeta - is one level up.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MCMETA     = "pack.mcmeta"
ROOT_FILES = ("pack.mcmeta", "pack.png", "README.md")   # packed, in this order
PACK_DIRS  = ("assets",)                                # packed, recursively
ZIP_DATE   = (1980, 1, 1, 0, 0, 0)                      # fixed: reproducible zip
VERSION_RE = re.compile(r"Plasticify\s+([0-9][0-9A-Za-z._+-]*)")
FMT_RE     = re.compile(r"\u00a7.")                     # Minecraft colour codes


def arg(flag):
    """--flag VALUE, or None (also accepts --flag=VALUE)."""
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None


def read_meta():
    """-> (pack_format, plain-text description)."""
    path = os.path.join(ROOT, MCMETA)
    if not os.path.isfile(path):
        sys.exit(f"no {MCMETA} in {ROOT} - is this the pack root?")
    try:
        meta = json.load(io.open(path, encoding="utf-8"))
    except ValueError as exc:
        sys.exit(f"{MCMETA} is not valid JSON: {exc}")
    block = meta.get("pack")
    if not isinstance(block, dict):
        sys.exit(f'{MCMETA} has no "pack" object')
    fmt = block.get("pack_format")
    if not isinstance(fmt, int):
        sys.exit(f'{MCMETA} has no integer "pack_format"')
    for key in ("min_format", "max_format"):
        val = block.get(key)
        if isinstance(val, int) and val != fmt:
            print(f"   ! {key}={val} does not match pack_format={fmt}")
        elif isinstance(val, list) and val[:1] != [fmt]:
            print(f"   ! {key}={val} does not cover pack_format={fmt}")
    return fmt, FMT_RE.sub("", str(block.get("description", "")))


def version_of(desc, override):
    if override:
        return override
    hit = VERSION_RE.search(desc)
    if not hit:
        sys.exit(f"no version in the pack description {desc!r} - pass --version")
    return hit.group(1)


def collect():
    """-> [(arcname, absolute path)]: the shippable whitelist, nothing else."""
    files, missing = [], []
    for name in ROOT_FILES:
        path = os.path.join(ROOT, name)
        if os.path.isfile(path):
            files.append((name, path))
        elif name in (MCMETA, "pack.png"):
            missing.append(name)
    for top in PACK_DIRS:
        base = os.path.join(ROOT, top)
        if not os.path.isdir(base):
            sys.exit(f"no {top}/ in {ROOT} - nothing to release")
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames.sort()
            for fn in sorted(filenames):
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                if rel.split("/", 1)[0] != top:             # symlink out of the pack
                    sys.exit(f"{rel} escapes {top}/")
                files.append((rel, path))
    if missing:
        print(f"   ! missing from the pack root: {', '.join(missing)}")
    if len(files) < 100:
        print(f"   ! only {len(files)} files - is assets/ populated?")
    return files


def report(files, fmt, version, desc):
    per = {}
    for arc, _ in files:
        top = arc.split("/", 1)[0]
        per[top] = per.get(top, 0) + 1
    total = sum(os.path.getsize(p) for _, p in files)
    print(f"pack        {ROOT}")
    print(f"version     {version}   (pack_format {fmt}, description {desc!r})")
    print(f"files       {len(files)}, {total / 1048576:.2f} MiB unpacked")
    for top in sorted(per):
        print(f"   {top:10} {per[top]}")


def write_zip(files, out):
    tmp = out + ".part"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for arc, path in files:
            info = zipfile.ZipInfo(arc, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with io.open(path, "rb") as src, zf.open(info, "w") as dst:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    dst.write(chunk)
    os.replace(tmp, out)


def check_zip(out, files):
    """Reopen the archive: an unloadable pack must never ship."""
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        bad = zf.testzip()
    if bad:
        sys.exit(f"corrupt entry in {out}: {bad}")
    if MCMETA not in names:
        sys.exit(f"{MCMETA} is not at the root of {out} - Minecraft loads this as empty")
    if len(names) != len(files):
        sys.exit(f"{len(names)} entries in {out}, expected {len(files)}")
    strays = [n for n in names
              if n not in ROOT_FILES and n.split("/", 1)[0] not in PACK_DIRS]
    if strays:
        sys.exit(f"unexpected entries in {out}: {strays[:5]}")
    return len(names)


def main():
    fmt, desc = read_meta()
    version = version_of(desc, arg("--version"))
    files = collect()
    report(files, fmt, version, desc)

    if "--list" in sys.argv:
        for arc, _ in files[:25]:
            print(f"   {arc}")
        if len(files) > 25:
            print(f"   ... and {len(files) - 25} more")
        return
    if "--check" in sys.argv:
        print("check only: nothing written")
        return

    out = arg("--out") or os.path.join(ROOT, "dist", f"Plasticify-{version}.zip")
    out = os.path.abspath(out)
    write_zip(files, out)
    entries = check_zip(out, files)
    print(f"\nwrote {out}")
    print(f"      {entries} entries, {os.path.getsize(out) / 1048576:.2f} MiB zipped")


if __name__ == "__main__":
    main()
