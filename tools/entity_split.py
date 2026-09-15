"""Per-folder recipe split for `textures/entity`.

Reads `_analysis/recipe_split.csv` (written by `build.py --list`) and prints, for
every entity folder, how many textures are kept versus quantised and at which
palette size.

Run it after changing a pin, to see a whole family move at once: the folder
column is what a "leave the X alone" request names.

    python tools/build.py --list      # writes the CSV this reads
    python tools/entity_split.py
"""
import collections
import csv
import io
import os

from common import ANALYSIS

CSV = os.path.join(ANALYSIS, "recipe_split.csv")


def main():
    rows = list(csv.DictReader(io.open(CSV, encoding="utf-8")))
    ent = [r for r in rows if r["texture"].startswith("entity/")]
    per_folder = collections.defaultdict(collections.Counter)
    for r in ent:
        folder = r["texture"].split("/")[1]
        per_folder[folder]["keep" if r["recipe"] == "keep" else "q" + r["palette"]] += 1

    print(f"entity textures: {len(ent)}   folders: {len(per_folder)}")
    for folder in sorted(per_folder):
        counts = per_folder[folder]
        quantised = sum(v for k, v in counts.items() if k != "keep")
        pinned = any(r["pinned"] and r["texture"].split("/")[1] == folder for r in ent)
        print(f"   {folder:18} keep={counts['keep']:3d} quantised={quantised:3d}  "
              f"{dict(sorted(counts.items()))}{'  <- pinned' if pinned else ''}")


if __name__ == "__main__":
    main()
