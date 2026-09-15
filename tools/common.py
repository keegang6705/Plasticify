"""Shared context for the Plasticify tools: the pack root and the vanilla jar.

Every tool here needs two things:

* the pack root - this repo, the folder holding `pack.mcmeta`
* vanilla Minecraft - a client jar, the source of the textures being plasticised

The jar is found in this order, and the first candidate that actually contains
vanilla textures wins:

1. `--jar PATH` on the command line
2. the `PLASTICIFY_JAR` environment variable
3. the usual launcher folders - Modrinth App, the official launcher, Prism
   Launcher, MultiMC - taking the newest release and falling back to a snapshot
   only when there is no release at all

Run `python tools/common.py` to see what it resolves; that is the first thing to
check when a tool cannot find Minecraft.
"""
import glob
import os
import re
import sys
import zipfile

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the pack repo
ANALYSIS = os.path.join(ROOT, "_analysis")      # dev output; git-ignored
TEXTURES = "assets/minecraft/textures/"
PROBE    = TEXTURES + "block/stone.png"         # present in every client jar

JAR_PATTERNS = (
    r"%APPDATA%\ModrinthApp\meta\versions\*\*.jar",
    r"%APPDATA%\.minecraft\versions\*\*.jar",
    r"%APPDATA%\PrismLauncher\instances\*\minecraft\versions\*\*.jar",
    r"%APPDATA%\MultiMC\instances\*\minecraft\versions\*\*.jar",
    "~/.minecraft/versions/*/*.jar",
    "~/.local/share/PrismLauncher/instances/*/minecraft/versions/*/*.jar",
    "~/Library/Application Support/minecraft/versions/*/*.jar",
)

_ZIP = None

# Launcher folders hold releases next to snapshots, pre-releases and weeklies:
# 26.2-0.19.5 and 26.2-snapshot-3, 1.21.4 and 1.21.4-pre1, 25w43a, b1.8.1.
_SNAPSHOT = re.compile(
    r"snapshot|\d{2}w\d{2}[a-z]?|pre|rc\d|beta|alpha|combat|experimental|^inf-|^rd-",
    re.I)


def arg(flag):
    """--flag VALUE, or None (also accepts --flag=VALUE)."""
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None


def _expand(pattern):
    return os.path.expanduser(os.path.expandvars(pattern))


def _is_client_jar(path):
    try:
        with zipfile.ZipFile(path) as z:
            return PROBE in z.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def _version_name(path):
    """The launcher's version folder name, e.g. '26.2-0.19.5'."""
    return os.path.basename(os.path.dirname(path))


def _version_key(path):
    """Sortable version name: digits padded, so 1.21.11 beats 1.21.4 and 26.2
    beats 25w43a - and a name that does not start with a digit (b1.8.1) counts
    as older than every release."""
    name = _version_name(path)
    padded = re.sub(r"\d+", lambda m: m.group(0).zfill(6), name)
    return (0 if name[:1].isdigit() else 1, padded)


def _pick(candidates):
    """The newest release; a snapshot only if there is no release at all."""
    releases = [p for p in candidates if not _SNAPSHOT.search(_version_name(p))]
    return max(releases or candidates, key=_version_key)


def find_jar(explicit=None):
    """-> path of a client jar holding vanilla textures, or exit with advice."""
    if explicit:
        if not os.path.isfile(explicit):
            sys.exit(f"no such jar: {explicit}")
        return explicit
    env = os.environ.get("PLASTICIFY_JAR")
    if env:
        if not os.path.isfile(env):
            sys.exit(f"PLASTICIFY_JAR is set but not a file: {env}")
        return env
    hits = []
    for pattern in JAR_PATTERNS:
        hits += [p for p in glob.glob(_expand(pattern)) if _is_client_jar(p)]
    if hits:
        return _pick(hits)
    sys.exit("cannot find a Minecraft client jar with vanilla textures.\n"
             "  pass one:  python tools/build.py --jar /path/to/client.jar\n"
             "  or set:    PLASTICIFY_JAR=/path/to/client.jar\n"
             "  looked in:\n    " + "\n    ".join(_expand(p) for p in JAR_PATTERNS))


def vanilla_zip():
    """The client jar, opened for reading and cached for this process."""
    global _ZIP
    if _ZIP is None:
        _ZIP = zipfile.ZipFile(find_jar(arg("--jar")))
    return _ZIP


def vanilla_textures(roots=("block", "entity", "item", "models")):
    """Sorted vanilla texture paths, relative to `assets/minecraft/textures`."""
    return sorted(n[len(TEXTURES):] for n in vanilla_zip().namelist()
                  if n.startswith(TEXTURES) and n.endswith(".png")
                  and n[len(TEXTURES):].split("/", 1)[0] in roots)


def read_vanilla(rel):
    """A vanilla texture as bytes; `rel` is relative to `assets/minecraft/textures`."""
    return vanilla_zip().read(TEXTURES + rel)


def main():
    print(f"pack root : {ROOT}")
    print(f"jar       : {find_jar(arg('--jar'))}")
    print(f"textures  : {len(vanilla_textures())}")
    print(f"analysis  : {ANALYSIS}")


if __name__ == "__main__":
    main()
