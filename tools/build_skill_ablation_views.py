#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

VIEWS = (
    "full",
    "description_only",
    "text_only",
    "no_validator",
    "no_route_guardrails",
)


def _skill_dirs(skills_root: Path) -> list[Path]:
    return sorted(
        path
        for path in skills_root.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )


def _frontmatter_description(text: str) -> str:
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---\n", 4)
    if end < 0:
        return ""
    data = yaml.safe_load(text[4:end]) or {}
    return str(data.get("description") or "").strip()


def _write_description_only(source: Path, target: Path) -> None:
    text = (source / "SKILL.md").read_text(encoding="utf-8")
    description = _frontmatter_description(text)
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(
        "---\n"
        f"name: {source.name}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n"
        "---\n",
        encoding="utf-8",
    )


def _copy_view(source: Path, target: Path, view: str) -> None:
    if view == "description_only":
        _write_description_only(source, target)
        return
    if view == "text_only":
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / "SKILL.md", target / "SKILL.md")
        return

    shutil.copytree(source, target)
    skill_path = target / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    if view == "no_validator":
        scripts = target / "scripts"
        if scripts.is_dir():
            for path in scripts.iterdir():
                if path.is_file() and "validat" in path.name.casefold():
                    path.unlink()
        text = "\n".join(
            line for line in text.splitlines() if "validat" not in line.casefold()
        )
        skill_path.write_text(text.rstrip() + "\n", encoding="utf-8")
    elif view == "no_route_guardrails":
        guardrail = re.compile(r"\bdo not (?:use|trigger)\b", re.IGNORECASE)
        text = "\n".join(line for line in text.splitlines() if not guardrail.search(line))
        skill_path.write_text(text.rstrip() + "\n", encoding="utf-8")


def build_views(
    skills_root: Path,
    output_root: Path,
    categories_path: Path | None = None,
) -> dict[str, Any]:
    skills = _skill_dirs(skills_root)
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    for view in VIEWS:
        for source in skills:
            _copy_view(source, output_root / view / source.name, view)

    categories: dict[str, Any] = {}
    if categories_path and categories_path.is_file():
        categories = yaml.safe_load(categories_path.read_text(encoding="utf-8")) or {}
    manifest = {
        "skill_count": len(skills),
        "skills": [path.name for path in skills],
        "views": list(VIEWS),
        "categories": categories.get("categories", categories),
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--categories", type=Path)
    args = parser.parse_args()
    manifest = build_views(args.skills_root, args.output_root, args.categories)
    print(f"[ok] skills={manifest['skill_count']} views={len(manifest['views'])}")


if __name__ == "__main__":
    main()
