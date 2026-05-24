#!/usr/bin/env python3
"""Generate one guidance style card per tutorial recipe."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_RECIPE_DIR = Path("knowledge/style_cards/tutorial_recipes")
DEFAULT_SUMMARY_PATH = DEFAULT_RECIPE_DIR / "tutorial_recipe_style_summary.md"
DEFAULT_FAMILY_DIR = Path("knowledge/style_cards/candidates")
DEFAULT_OUTPUT_DIR = Path("knowledge/style_cards/tutorial_derived")

FAMILY_FALLBACKS: dict[str, dict[str, Any]] = {
    "japanese_clean_portrait": {
        "style_name": "日系干净人像",
        "suitable_scenes": ["自然光人像", "日常记录", "浅色街景"],
        "avoid_scenes": ["强夜景", "高反差舞台光"],
        "visual_features": {
            "tone": "bright, clean, soft",
            "color": "clean skin, reduced dirty greens",
            "contrast": "low-medium",
            "texture": "soft and low clarity",
        },
        "agent_guidance": ["保持画面明亮通透，优先保护肤色和高光。"],
    },
    "japanese_film_gray": {
        "style_name": "日系胶片灰",
        "suitable_scenes": ["阴天街景", "生活纪实", "胶片感人像"],
        "avoid_scenes": ["高饱和商业片", "需要纯净白底的照片"],
        "visual_features": {
            "tone": "muted gray, lifted shadows",
            "color": "low saturation, warm skin",
            "contrast": "soft with film-like rolloff",
            "texture": "subtle grain",
        },
        "agent_guidance": ["用曲线和 HSL 做低饱和胶片灰，不要把照片调脏。"],
    },
    "warm_portrait_sunset": {
        "style_name": "暖系人像与日落氛围",
        "suitable_scenes": ["日落", "秋季外景", "暖光人像"],
        "avoid_scenes": ["冷调夜景", "需要真实中性色的产品图"],
        "visual_features": {
            "tone": "warm and atmospheric",
            "color": "orange-yellow warmth with controlled cyan",
            "contrast": "medium",
            "texture": "clean but tactile",
        },
        "agent_guidance": ["先找光线方向和暖色来源，再决定整体暖化幅度。"],
    },
    "cinematic_street_night": {
        "style_name": "电影感街拍夜景",
        "suitable_scenes": ["街拍", "雨夜", "霓虹", "城市夜景"],
        "avoid_scenes": ["明亮儿童照", "柔和日系人像"],
        "visual_features": {
            "tone": "cinematic, deep but readable",
            "color": "cool shadows, controlled warm highlights",
            "contrast": "medium-high",
            "texture": "crisp urban texture",
        },
        "agent_guidance": ["保留夜景层次，不要把阴影全部压死。"],
    },
    "dark_low_saturation_moody": {
        "style_name": "低饱暗调质感",
        "suitable_scenes": ["暗调人像", "情绪片", "低照度环境"],
        "avoid_scenes": ["小清新人像", "明亮旅行记录"],
        "visual_features": {
            "tone": "dark, restrained",
            "color": "low saturation with selective warmth",
            "contrast": "strong local contrast",
            "texture": "tactile and moody",
        },
        "agent_guidance": ["压暗时保留主体轮廓和肤色可读性。"],
    },
    "dreamy_pastel_anime": {
        "style_name": "梦幻粉紫动漫感",
        "suitable_scenes": ["夜景人像", "粉紫天空", "梦幻氛围照片"],
        "avoid_scenes": ["纪实街拍", "需要真实色彩的照片"],
        "visual_features": {
            "tone": "dreamy and luminous",
            "color": "pink-purple pastel with blue accents",
            "contrast": "soft",
            "texture": "smooth and stylized",
        },
        "agent_guidance": ["粉紫色要服务氛围，避免肤色过度偏紫。"],
    },
    "cyan_blue_story": {
        "style_name": "青蓝故事感",
        "suitable_scenes": ["街头人像", "环境人像", "阴天城市"],
        "avoid_scenes": ["暖调日落", "高饱和花草"],
        "visual_features": {
            "tone": "quiet and narrative",
            "color": "cyan-blue bias with controlled skin warmth",
            "contrast": "medium",
            "texture": "natural documentary texture",
        },
        "agent_guidance": ["青蓝氛围不能牺牲主体肤色，必要时局部保护人物。"],
    },
    "master_reference_texture": {
        "style_name": "大师仿色质感",
        "suitable_scenes": ["参考图仿色", "人像", "旅行", "综合练习"],
        "avoid_scenes": ["没有明确参考方向的批量套色"],
        "visual_features": {
            "tone": "reference-driven",
            "color": "match dominant reference palette",
            "contrast": "case-specific",
            "texture": "case-specific photographer texture",
        },
        "agent_guidance": ["先分析参考图的光线、色相和明暗关系，再生成参数。"],
    },
    "black_white_street_grain": {
        "style_name": "黑白街头颗粒",
        "suitable_scenes": ["黑白街拍", "高反差纪实", "颗粒感照片"],
        "avoid_scenes": ["依赖色彩表达的照片", "柔和儿童或婚礼照片"],
        "visual_features": {
            "tone": "monochrome, high impact",
            "color": "black and white only",
            "contrast": "strong",
            "texture": "visible grain and street grit",
        },
        "agent_guidance": ["黑白转换后用明暗结构和颗粒承担风格表达。"],
    },
}

FAMILY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("black_white_street_grain", ["黑白", "森山大道", "monochrome", "black white"]),
    ("dreamy_pastel_anime", ["梦幻", "粉紫", "动漫", "pastel", "anime", "romantic"]),
    ("dark_low_saturation_moody", ["暗调", "低饱", "低饱和", "moody", "dark", "暗黑"]),
    ("cinematic_street_night", ["街拍", "夜景", "雨夜", "霓虹", "电影感", "street", "night", "cinematic", "rain"]),
    ("warm_portrait_sunset", ["暖色", "暖系", "日落", "秋季", "紫霞", "暖青", "sunset", "warm"]),
    ("japanese_film_gray", ["胶片", "复古", "日杂", "阴天", "柯达", "富士", "film", "kodak", "fuji", "gray"]),
    ("japanese_clean_portrait", ["日系", "清新", "干净", "小清新", "韩系", "通透", "clean"]),
    ("cyan_blue_story", ["青蓝", "故事感", "蓝调", "cyan", "blue story"]),
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_summary_mapping(summary_text: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line in summary_text.splitlines():
        if not line.startswith("| `bilibili_"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        recipe_id = cells[0].strip("`")
        family = cells[4].strip("`")
        if recipe_id and family:
            mapping[recipe_id] = family
    return mapping


def load_family_cards(family_dir: Path) -> dict[str, dict[str, Any]]:
    cards = {key: dict(value) for key, value in FAMILY_FALLBACKS.items()}
    if not family_dir.exists():
        return cards

    for path in family_dir.glob("*.json"):
        payload = read_json(path)
        style_id = payload.get("style_id")
        if not style_id:
            continue
        fallback = cards.get(style_id, {})
        cards[style_id] = {
            "style_name": payload.get("style_name", fallback.get("style_name", style_id)),
            "suitable_scenes": payload.get("suitable_scenes", fallback.get("suitable_scenes", [])),
            "avoid_scenes": payload.get("avoid_scenes", fallback.get("avoid_scenes", [])),
            "visual_features": normalize_visual_features(
                payload.get("visual_features", fallback.get("visual_features", {}))
            ),
            "agent_guidance": payload.get("agent_guidance", fallback.get("agent_guidance", [])),
        }
    return cards


def infer_style_family(recipe: dict[str, Any]) -> str:
    source = recipe.get("source", {})
    transcript = recipe.get("transcript", {})
    extraction = recipe.get("extraction", {})
    text_parts = [
        str(source.get("title", "")),
        str(transcript.get("excerpt", "")),
        " ".join(str(keyword) for keyword in extraction.get("matched_keywords", [])),
    ]
    haystack = "\n".join(text_parts).lower()
    scores: dict[str, int] = {}
    for family_id, keywords in FAMILY_KEYWORDS:
        score = sum(1 for keyword in keywords if keyword.lower() in haystack)
        if score:
            scores[family_id] = score
    if scores:
        return max(scores.items(), key=lambda item: item[1])[0]
    return "master_reference_texture"


def normalize_visual_features(features: dict[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in features.items():
        normalized[key] = str(value)
    return normalized


def extract_series_label(title: str) -> str:
    match = re.search(r"追色手记\s*([0-9]+)", title)
    if match:
        return f"追色手记{match.group(1)}"
    match = re.search(r"调色日记", title)
    if match:
        return "调色日记"
    return ""


def compact_title(title: str, limit: int = 42) -> str:
    cleaned = re.sub(r"【[^】]*】", "", title)
    cleaned = re.sub(r"（[^）]*(赠送|附|素材|预设)[^）]*）", "", cleaned)
    cleaned = re.sub(r"\([^)]*(赠送|附|素材|预设)[^)]*\)", "", cleaned)
    cleaned = re.sub(r"[｜|].*$", "", cleaned).strip(" 　-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) <= limit:
        return cleaned or title[:limit]
    return cleaned[: limit - 1].rstrip() + "…"


def style_name_for_recipe(recipe: dict[str, Any], family: dict[str, Any]) -> str:
    title = recipe.get("source", {}).get("title", "")
    series = extract_series_label(title)
    compact = compact_title(title)
    if series and series not in compact:
        return f"{series}: {compact}"
    if compact:
        return compact
    return f"{family.get('style_name', '教程风格')}变体"


def scene_hints(title: str, family_scenes: list[str]) -> list[str]:
    hints = list(family_scenes[:3])
    rules = [
        ("人像", "人像"),
        ("街", "街拍"),
        ("夜", "夜景"),
        ("雨", "雨天"),
        ("日落", "日落"),
        ("风光", "风光"),
        ("旅行", "旅行"),
        ("建筑", "建筑"),
        ("黑白", "黑白"),
        ("胶片", "胶片感"),
        ("手机", "手机照片"),
    ]
    for keyword, hint in rules:
        if keyword in title and hint not in hints:
            hints.append(hint)
    return hints[:6]


def category_counts(steps: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(step.get("category", "unknown")) for step in steps))


def operation_order_from_steps(steps: list[dict[str, Any]]) -> list[str]:
    order: list[str] = []
    category_map = {
        "basic_tone": "exposure_and_basic_tone",
        "tone_curve": "tone_curve",
        "color": "global_color_balance",
        "hsl": "hsl_color_cleanup",
        "detail": "detail_and_texture",
        "mask": "local_adjustments",
        "local": "local_adjustments",
        "grading": "color_grading",
        "export": "final_review",
    }
    for step in steps:
        category = str(step.get("category", "unknown")).lower()
        operation = category_map.get(category, category.replace(" ", "_"))
        if operation and operation not in order:
            order.append(operation)
    if not order:
        order = ["white_balance", "exposure", "tone_curve", "color_cleanup", "final_review"]
    if "final_review" not in order:
        order.append("final_review")
    return order[:8]


def representative_steps(steps: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_categories: set[str] = set()

    for step in steps:
        category = str(step.get("category", "unknown"))
        if category in seen_categories:
            continue
        selected.append(step)
        seen_categories.add(category)
        if len(selected) >= limit:
            return selected

    for step in steps:
        if step in selected:
            continue
        selected.append(step)
        if len(selected) >= limit:
            break
    return selected


def step_guidance(steps: list[dict[str, Any]], limit: int = 6) -> list[str]:
    guidance: list[str] = []
    for step in representative_steps(steps, limit=limit):
        text = str(step.get("text", "")).strip()
        if not text:
            continue
        if len(text) > 90:
            text = text[:89].rstrip() + "…"
        guidance.append(text)
    return guidance


def build_visual_intent(recipe: dict[str, Any], family: dict[str, Any]) -> str:
    title = recipe.get("source", {}).get("title", "")
    family_name = family.get("style_name", "教程风格")
    compact = compact_title(title, limit=60)
    if compact:
        return f"以“{compact}”为来源的{family_name}视频级变体，重点保留该教程的题材、色彩倾向和局部处理顺序。"
    return f"从单条教程字幕中抽取的{family_name}视频级变体。"


def build_tone_guidance(family: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, str]:
    features = family.get("visual_features", {})
    guidance = {
        "overall": str(features.get("tone", "infer brightness and contrast from the source photo")),
        "contrast": str(features.get("contrast", "adjust per photo; avoid clipping important detail")),
        "texture": str(features.get("texture", "match texture intensity to subject and noise level")),
    }
    text = " ".join(str(step.get("text", "")) for step in steps)
    if "高光" in text or "亮部" in text or "highlight" in text.lower():
        guidance["highlights"] = "protect highlight detail and decide compression from the actual preview"
    if "阴影" in text or "暗部" in text or "shadow" in text.lower():
        guidance["shadows"] = "preserve subject readability; do not crush shadows blindly"
    return guidance


def build_color_guidance(family: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, str]:
    features = family.get("visual_features", {})
    guidance = {
        "overall": str(features.get("color", "infer color direction from the style family and source photo")),
    }
    text = " ".join(str(step.get("text", "")) for step in steps)
    color_rules = [
        ("肤色", "skin", "protect believable skin tone; avoid green, gray, or over-orange skin"),
        ("橙色", "orange", "adjust orange from subject context, especially skin and warm light"),
        ("绿色", "greens", "clean up distracting or dirty greens when they compete with the subject"),
        ("蓝色", "blues", "use blues to support atmosphere without making the frame look artificial"),
        ("色温", "white_balance", "choose temperature from actual light and desired mood"),
        ("色调", "tint", "use tint only to correct cast or support the chosen style"),
    ]
    for keyword, key, value in color_rules:
        if keyword in text and key not in guidance:
            guidance[key] = value
    return guidance


def build_card(
    recipe: dict[str, Any],
    style_family: str,
    family_cards: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    recipe_id = recipe["recipe_id"]
    source = recipe.get("source", {})
    transcript = recipe.get("transcript", {})
    extraction = recipe.get("extraction", {})
    steps = extraction.get("steps", [])
    family = family_cards.get(style_family, FAMILY_FALLBACKS.get(style_family, {}))
    title = source.get("title", "")

    return {
        "schema_version": "lumenflow.style_card.tutorial_derived.v1",
        "style_id": f"tutorial_{recipe_id}",
        "style_name": style_name_for_recipe(recipe, family),
        "status": "candidate",
        "card_role": "style_guidance",
        "source_scope": "single_bilibili_tutorial_recipe",
        "source_recipe": recipe_id,
        "source_video": {
            "platform": source.get("platform"),
            "bvid": source.get("bvid"),
            "url": source.get("url"),
            "title": title,
            "language": source.get("language"),
            "segment_count": transcript.get("segment_count", 0),
            "step_count": len(steps),
            "transcript_path": transcript.get("path"),
        },
        "style_family": {
            "style_id": style_family,
            "style_name": family.get("style_name", style_family),
        },
        "visual_intent": build_visual_intent(recipe, family),
        "suitable_scenes": scene_hints(title, list(family.get("suitable_scenes", []))),
        "avoid_scenes": family.get("avoid_scenes", []),
        "visual_features": family.get("visual_features", {}),
        "tone_guidance": build_tone_guidance(family, steps),
        "color_guidance": build_color_guidance(family, steps),
        "operation_order": operation_order_from_steps(steps),
        "parameter_strategy": "agent_infers_per_photo",
        "adjustment_plan_guidance": {
            "schema_version": "lumenflow.adjustment_plan.v1",
            "rule": "Use this card to reason about direction only. The agent must inspect the target photo and generate concrete values in adjustment_plan.json.",
            "variant_policy": "Generate one best variant by default; add alternates only when multiple styles genuinely fit the photo.",
        },
        "agent_guidance": list(family.get("agent_guidance", []))[:4]
        + [
            "具体参数必须由 agent 根据输入照片重新推理，不直接套用字幕中的固定数值。",
            "先判断照片是否匹配该视频题材；不匹配时只借鉴色彩思路，不强套完整风格。",
        ],
        "tutorial_guidance": step_guidance(steps),
        "evidence": {
            "matched_keywords": extraction.get("matched_keywords", []),
            "category_counts": category_counts(steps),
            "representative_steps": representative_steps(steps),
        },
        "raw_profile_role": "none",
        "raw_profiles": [],
        "review_notes": "One guidance card per source video. Treat as candidate reasoning material; do not convert transcript numbers into fixed presets without photo-specific agent review.",
    }


def load_recipes(recipe_dir: Path) -> list[dict[str, Any]]:
    recipes = []
    for path in sorted(recipe_dir.glob("*.json")):
        recipes.append(read_json(path))
    return recipes


def write_index(output_dir: Path, cards: list[dict[str, Any]]) -> Path:
    lines = [
        "# Tutorial Derived Style Cards",
        "",
        "Generated one guidance style card per successful tutorial recipe. These cards guide agent reasoning; they are not executable presets.",
        "",
        "| style_id | family | language | steps | title |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for card in cards:
        video = card["source_video"]
        family = card["style_family"]
        lines.append(
            "| `{}` | `{}` | {} | {} | {} |".format(
                card["style_id"],
                family["style_id"],
                video.get("language") or "",
                video.get("step_count") or 0,
                video.get("title") or "",
            )
        )
    index_path = output_dir / "index.md"
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index_path


def generate_cards(
    recipe_dir: Path,
    summary_path: Path,
    family_dir: Path,
    output_dir: Path,
) -> list[Path]:
    summary_mapping = parse_summary_mapping(summary_path.read_text(encoding="utf-8"))
    family_cards = load_family_cards(family_dir)
    recipes = load_recipes(recipe_dir)

    cards: list[dict[str, Any]] = []
    written: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    stale_files = {path for path in output_dir.glob("*.json")}
    for recipe in recipes:
        recipe_id = recipe["recipe_id"]
        style_family = summary_mapping.get(recipe_id) or infer_style_family(recipe)
        card = build_card(recipe, style_family, family_cards)
        cards.append(card)
        path = output_dir / f"{card['style_id']}.json"
        write_json(path, card)
        stale_files.discard(path)
        written.append(path)

    for stale_file in stale_files:
        stale_file.unlink()

    write_index(output_dir, cards)
    return written


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe-dir", type=Path, default=DEFAULT_RECIPE_DIR)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--family-dir", type=Path, default=DEFAULT_FAMILY_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    written = generate_cards(
        recipe_dir=args.recipe_dir,
        summary_path=args.summary,
        family_dir=args.family_dir,
        output_dir=args.output_dir,
    )
    print(f"Generated {len(written)} tutorial-derived style cards in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
