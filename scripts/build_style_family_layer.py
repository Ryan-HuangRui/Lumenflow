#!/usr/bin/env python3
"""Merge private tutorial evidence into reusable, source-clean style knowledge."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_RECIPE_DIR = Path("knowledge/style_cards/tutorial_recipes")
DEFAULT_CARD_DIR = Path("knowledge/style_cards/tutorial_derived")
DEFAULT_FAMILY_DIR = Path("knowledge/style_families")
DEFAULT_INDEX_PATH = Path("knowledge/style_library_index.json")
DEFAULT_PROVENANCE_PATH = Path("knowledge/private_provenance/style_source_map.json")
DEFAULT_SUMMARY_PATH = DEFAULT_RECIPE_DIR / "tutorial_recipe_style_summary.md"

FORBIDDEN_PUBLIC_KEYS = {
    "bvid",
    "representative_steps",
    "representative_variants",
    "source_recipe",
    "source_video",
    "title",
    "transcript_path",
    "tutorial_variants",
    "url",
}

CATEGORY_OPERATION_MAP = {
    "basic_tone": "exposure_and_basic_tone",
    "tone_curve": "tone_curve",
    "color": "global_color_balance",
    "hsl": "hsl_color_cleanup",
    "detail": "detail_and_texture",
    "mask": "local_adjustments",
    "local": "local_adjustments",
    "grading": "color_grading",
    "export": "final_review",
    "color_grading": "color_grading",
    "hsl_color": "hsl_color_cleanup",
    "mask_local": "local_adjustments",
    "presence_detail": "detail_and_texture",
}

PUBLISHABLE_ROLES = {"visual_style", "method_family"}


FAMILY_DEFINITIONS: dict[str, dict[str, Any]] = {
    "japanese_clean_portrait": {
        "style_family_name": "日系干净人像",
        "role": "visual_style",
        "parent_family": "clean_bright_portrait",
        "active_for_photo_matching": True,
        "description": "明亮、干净、柔和的日系人像与日常记录方向，重点是去脏、保肤色和通透感。",
        "suitable_scenes": ["自然光人像", "日常记录", "浅色街景", "樱花或夏日外景"],
        "avoid_scenes": ["强夜景", "高反差商业片", "需要浓重情绪的暗调照片"],
        "visual_features": {
            "tone": "bright, clean, soft",
            "color": "clean skin, controlled greens, gentle warm highlights",
            "contrast": "low-medium",
            "texture": "soft clarity and low dirty color cast",
        },
        "agent_guidance": [
            "先处理画面发黄、发灰、发脏的问题，再决定整体亮度。",
            "肤色和白色物体优先保持可信，绿色只做清理不做过度风格化。",
        ],
    },
    "japanese_transparent_backlight": {
        "style_family_name": "日系通透逆光",
        "role": "visual_style",
        "parent_family": "clean_bright_portrait",
        "active_for_photo_matching": True,
        "description": "逆光、硬光或灰暗原片中提炼通透感，强调高光保护、脸部提亮和空气感。",
        "suitable_scenes": ["逆光人像", "硬光人像", "灰暗人像", "透明感外景"],
        "avoid_scenes": ["夜景霓虹", "需要厚重阴影的照片"],
        "visual_features": {
            "tone": "transparent, airy, lifted subject",
            "color": "warm skin with clean cool environment",
            "contrast": "soft global contrast with local subject lift",
            "texture": "low haze and gentle detail",
        },
        "agent_guidance": [
            "先判断主体是否因为逆光变暗，再用局部调整恢复脸部可读性。",
            "高光压缩要保留光感，不能把逆光调成平光。",
        ],
    },
    "japanese_film_gray": {
        "style_family_name": "日系胶片灰",
        "role": "visual_style",
        "parent_family": "film_muted",
        "active_for_photo_matching": True,
        "description": "低饱和、柔对比、轻微灰调的日系胶片感，适合阴天、街景和生活纪实。",
        "suitable_scenes": ["阴天街景", "生活纪实", "胶片感人像", "日杂风照片"],
        "avoid_scenes": ["高饱和商业片", "通透高亮人像", "浓烈日落"],
        "visual_features": {
            "tone": "muted gray with lifted shadows",
            "color": "low saturation, warm skin, restrained greens",
            "contrast": "soft with film-like rolloff",
            "texture": "subtle grain and gentle clarity",
        },
        "agent_guidance": [
            "灰调应来自曲线和饱和度控制，不要把白色和肤色调脏。",
            "阴影可以抬起，但主体边界仍要清楚。",
        ],
    },
    "korean_soft_portrait": {
        "style_family_name": "韩系柔和人像",
        "role": "visual_style",
        "parent_family": "clean_bright_portrait",
        "active_for_photo_matching": True,
        "description": "韩系、柔和、小清新人像方向，弱化硬对比，保留细腻肤色和轻盈氛围。",
        "suitable_scenes": ["女性人像", "儿童摄影", "柔光人像", "浅色户外"],
        "avoid_scenes": ["高反差街拍", "暗黑题材", "粗颗粒纪实"],
        "visual_features": {
            "tone": "soft, light, gentle",
            "color": "delicate skin, fresh greens, low color cast",
            "contrast": "low",
            "texture": "smooth but not plastic",
        },
        "agent_guidance": [
            "优先控制肤色和面部亮度，避免用过高锐化破坏柔和感。",
            "如果原片光线很硬，用局部和高光压缩降低攻击性。",
        ],
    },
    "warm_sunset_portrait": {
        "style_family_name": "暖调日落人像",
        "role": "visual_style",
        "parent_family": "warm_atmosphere",
        "active_for_photo_matching": True,
        "description": "日落、黄昏、秋季暖光人像，强调暖色来源、层次和主体肤色。",
        "suitable_scenes": ["日落人像", "黄昏逆光", "秋季外景", "暖光街景"],
        "avoid_scenes": ["冷调夜景", "需要中性还原的产品图"],
        "visual_features": {
            "tone": "warm and atmospheric",
            "color": "orange-yellow warmth with controlled cyan contrast",
            "contrast": "medium",
            "texture": "clean but tactile",
        },
        "agent_guidance": [
            "先找真实暖光来源，再决定整体暖化幅度。",
            "暖调不能让肤色过橙，必要时用 HSL 单独保护橙色。",
        ],
    },
    "warm_family_lifestyle": {
        "style_family_name": "暖调家庭生活",
        "role": "visual_style",
        "parent_family": "warm_atmosphere",
        "active_for_photo_matching": True,
        "description": "家庭照、婚礼和日常生活的温暖叙事方向，偏柔和、亲近、低攻击性。",
        "suitable_scenes": ["家庭照", "婚礼纪实", "亲子", "日常室内外生活"],
        "avoid_scenes": ["冷峻街拍", "高饱和霓虹", "黑白纪实"],
        "visual_features": {
            "tone": "warm, intimate, gentle",
            "color": "warm skin, soft highlights, restrained greens",
            "contrast": "low-medium",
            "texture": "natural and forgiving",
        },
        "agent_guidance": [
            "风格强度要服务人物关系，避免为了色彩牺牲表情和生活质感。",
            "优先保证肤色、白色衣物和室内光线自然。",
        ],
    },
    "cyan_blue_story_portrait": {
        "style_family_name": "青蓝故事感人像",
        "role": "visual_style",
        "parent_family": "cool_narrative",
        "active_for_photo_matching": True,
        "description": "青蓝偏冷的故事感人像与环境人像，用冷背景衬托主体暖肤色。",
        "suitable_scenes": ["街头人像", "环境人像", "阴天城市", "蓝绿色背景"],
        "avoid_scenes": ["暖调日落", "高饱和花草", "儿童暖调生活照"],
        "visual_features": {
            "tone": "quiet and narrative",
            "color": "cyan-blue bias with protected skin warmth",
            "contrast": "medium",
            "texture": "natural documentary texture",
        },
        "agent_guidance": [
            "青蓝氛围不能牺牲主体肤色，必要时用局部或 HSL 保护人物。",
            "如果原片没有冷色环境，只借鉴压饱和和叙事对比思路。",
        ],
    },
    "rainy_cinematic_street": {
        "style_family_name": "雨夜电影街拍",
        "role": "visual_style",
        "parent_family": "cinematic_street",
        "active_for_photo_matching": True,
        "description": "雨夜、湿地面、霓虹反光和街头电影感，强调暗部层次与冷暖光源。",
        "suitable_scenes": ["雨夜街拍", "夜景人像", "湿地面反光", "城市路灯"],
        "avoid_scenes": ["明亮儿童照", "柔和日系人像", "纯自然风光"],
        "visual_features": {
            "tone": "cinematic, deep but readable",
            "color": "cool shadows, warm highlights, controlled neon",
            "contrast": "medium-high",
            "texture": "crisp urban texture",
        },
        "agent_guidance": [
            "压暗时保留主体轮廓、灯牌和地面反光层次。",
            "霓虹颜色可以增强，但不要让皮肤或天空产生脏色块。",
        ],
    },
    "urban_neon_night": {
        "style_family_name": "都市霓虹夜景",
        "role": "visual_style",
        "parent_family": "cinematic_street",
        "active_for_photo_matching": True,
        "description": "城市夜景、霓虹、蓝紫或青橙光源的高度风格化夜景方向。",
        "suitable_scenes": ["城市夜景", "霓虹街区", "夜景人像", "蓝紫光源"],
        "avoid_scenes": ["自然光清新人像", "低饱和纪实"],
        "visual_features": {
            "tone": "dark luminous city night",
            "color": "blue-purple or cyan-orange neon palette",
            "contrast": "medium-high with highlight glow",
            "texture": "sharp lights and controlled noise",
        },
        "agent_guidance": [
            "优先控制噪点和高光溢出，再强化霓虹色彩。",
            "如果照片主体是人，霓虹色不能完全污染肤色。",
        ],
    },
    "street_light_shadow_cinematic": {
        "style_family_name": "街头光影电影感",
        "role": "visual_style",
        "parent_family": "cinematic_street",
        "active_for_photo_matching": True,
        "description": "扫街、街头光影、电影感色彩和中高对比叙事照片。",
        "suitable_scenes": ["扫街", "街头光影", "旅行街景", "人文纪实"],
        "avoid_scenes": ["纯净柔光人像", "需要明亮透明的照片"],
        "visual_features": {
            "tone": "cinematic street contrast",
            "color": "restrained palette with warm-cool separation",
            "contrast": "medium-high local contrast",
            "texture": "visible street detail",
        },
        "agent_guidance": [
            "先判断光影结构是否成立，再加对比和色彩分离。",
            "街拍质感来自明暗关系，不要只靠降曝光制造电影感。",
        ],
    },
    "dark_low_saturation_moody": {
        "style_family_name": "低饱暗调质感",
        "role": "visual_style",
        "parent_family": "moody_dark",
        "active_for_photo_matching": True,
        "description": "低饱和、暗调、质感化的人像或环境照片，强调情绪和主体可读性。",
        "suitable_scenes": ["暗调人像", "情绪片", "低照度环境", "硬朗质感照片"],
        "avoid_scenes": ["小清新人像", "明亮旅行记录", "家庭暖调照片"],
        "visual_features": {
            "tone": "dark, restrained, tactile",
            "color": "low saturation with selective warmth",
            "contrast": "strong local contrast",
            "texture": "tactile and moody",
        },
        "agent_guidance": [
            "压暗时保留主体边缘和眼神/关键细节。",
            "饱和度降低后要检查肤色是否灰绿。",
        ],
    },
    "forest_moss_green": {
        "style_family_name": "森系墨绿低饱和",
        "role": "visual_style",
        "parent_family": "moody_nature",
        "active_for_photo_matching": True,
        "description": "森系、墨绿、低饱和黄绿和深色自然氛围，适合森林、旅行生活方式照片。",
        "suitable_scenes": ["森林", "草地", "户外生活方式", "旅行故事"],
        "avoid_scenes": ["城市霓虹", "高饱和花海", "需要鲜亮绿色的照片"],
        "visual_features": {
            "tone": "deep natural mood",
            "color": "moss green, muted yellow-green, warm skin",
            "contrast": "medium with dark greens",
            "texture": "organic and calm",
        },
        "agent_guidance": [
            "绿色要从鲜绿压向墨绿或黄绿，但不要让植物变成死黑。",
            "如果有人像，优先保护肤色和脸部亮度。",
        ],
    },
    "dreamy_pastel_anime": {
        "style_family_name": "梦幻粉紫动漫感",
        "role": "visual_style",
        "parent_family": "dreamy_stylized",
        "active_for_photo_matching": True,
        "description": "粉紫、动漫感、梦幻夜景或天空方向，强调柔和色彩和氛围化高光。",
        "suitable_scenes": ["粉紫天空", "夜景人像", "动漫感风光", "梦幻氛围照片"],
        "avoid_scenes": ["纪实街拍", "需要真实色彩的照片", "严肃商务照片"],
        "visual_features": {
            "tone": "dreamy and luminous",
            "color": "pink-purple pastel with blue accents",
            "contrast": "soft",
            "texture": "smooth and stylized",
        },
        "agent_guidance": [
            "粉紫色要服务天空、灯光或氛围，避免肤色过度偏紫。",
            "梦幻感通常需要降低局部攻击性，但主体仍要清楚。",
        ],
    },
    "blue_hour_travel_night": {
        "style_family_name": "蓝调时刻旅拍夜景",
        "role": "visual_style",
        "parent_family": "cool_narrative",
        "active_for_photo_matching": True,
        "description": "蓝调时刻、旅行夜景、冷色天空与暖光点缀的旅拍方向。",
        "suitable_scenes": ["蓝调时刻", "旅行夜景", "城市天际线", "夜晚街景"],
        "avoid_scenes": ["正午人像", "室内暖调家庭照"],
        "visual_features": {
            "tone": "cool evening atmosphere",
            "color": "deep blue base with warm light accents",
            "contrast": "medium",
            "texture": "clean night detail",
        },
        "agent_guidance": [
            "保留蓝调时刻的天空层次，暖光只作为点缀。",
            "先控噪和暗部可读性，再推蓝色氛围。",
        ],
    },
    "landscape_blue_green_epic": {
        "style_family_name": "风光蓝绿大片",
        "role": "visual_style",
        "parent_family": "landscape_cinematic",
        "active_for_photo_matching": True,
        "description": "风光、航拍、户外探险和史诗感蓝绿调，强调空间层次和大场景冲击力。",
        "suitable_scenes": ["风光", "航拍", "山川湖海", "户外探险", "史诗感旅行"],
        "avoid_scenes": ["近景柔光人像", "室内生活照"],
        "visual_features": {
            "tone": "epic landscape depth",
            "color": "blue-green/cyan landscape palette with warm accents",
            "contrast": "medium-high with protected highlights",
            "texture": "clear terrain and sky detail",
        },
        "agent_guidance": [
            "风光大片先建立天空、地面和远近层次，再增强蓝绿或暖色对比。",
            "避免为了通透过度去朦胧导致边缘发硬。",
        ],
    },
    "landscape_mask_light_rebuild": {
        "style_family_name": "风光蒙版光影重塑",
        "role": "method_family",
        "parent_family": "landscape_cinematic",
        "active_for_photo_matching": True,
        "description": "风光照片中用蒙版、径向、渐变等局部工具重塑光影层次的方法型家族。",
        "suitable_scenes": ["风光", "航拍", "日落风光", "层次不足的大场景"],
        "avoid_scenes": ["已经有强烈自然光影的照片", "要求纪实还原的照片"],
        "visual_features": {
            "tone": "locally sculpted landscape light",
            "color": "case-specific landscape color",
            "contrast": "local contrast and selective brightness",
            "texture": "enhanced but controlled detail",
        },
        "agent_guidance": [
            "先判断原片光线结构，再用蒙版补光或压暗，不要平均化全图。",
            "每个局部调整都要有视觉目的：引导视线、增加层次或保护高光。",
        ],
    },
    "fuji_kodak_film_simulation": {
        "style_family_name": "富士柯达胶片模拟",
        "role": "visual_style",
        "parent_family": "film_muted",
        "active_for_photo_matching": True,
        "description": "富士、柯达、Cinestill 等具体胶片模拟方向，强调曲线、色偏和颗粒质感。",
        "suitable_scenes": ["胶片模拟", "日常旅行", "街景", "生活方式照片"],
        "avoid_scenes": ["需要精准还原色彩的照片", "过曝严重的照片"],
        "visual_features": {
            "tone": "film stock inspired rolloff",
            "color": "stock-specific hue shifts and restrained saturation",
            "contrast": "stock-specific curve contrast",
            "texture": "grain or film-like softness",
        },
        "agent_guidance": [
            "先明确要模拟的是哪类胶片倾向，再决定曲线和色彩分离。",
            "胶片感不是简单加颗粒，必须同时处理高光过渡和暗部密度。",
        ],
    },
    "black_white_street_grain": {
        "style_family_name": "黑白街头颗粒",
        "role": "visual_style",
        "parent_family": "monochrome",
        "active_for_photo_matching": True,
        "description": "黑白街头、高反差、颗粒和纪实冲击力方向。",
        "suitable_scenes": ["黑白街拍", "高反差纪实", "颗粒感照片", "强光影结构"],
        "avoid_scenes": ["依赖色彩表达的照片", "柔和儿童或婚礼照片"],
        "visual_features": {
            "tone": "monochrome, high impact",
            "color": "black and white only",
            "contrast": "strong",
            "texture": "visible grain and street grit",
        },
        "agent_guidance": [
            "黑白转换后用明暗结构和颗粒承担风格表达。",
            "如果照片的核心是色彩关系，不要强转黑白。",
        ],
    },
    "photographer_reference_texture": {
        "style_family_name": "摄影师仿色质感",
        "role": "visual_style",
        "parent_family": "reference_style",
        "active_for_photo_matching": True,
        "description": "无法稳定归入单一色系、但明确围绕某位摄影师或案例建立的仿色质感方向。",
        "suitable_scenes": ["摄影师风格仿色", "旅行人像", "环境人像", "多案例参考"],
        "avoid_scenes": ["没有相近光线或题材却强行套用参考", "需要严格中性还原的照片"],
        "visual_features": {
            "tone": "reference-driven photographer texture",
            "color": "case-specific palette inferred from a chosen visual reference",
            "contrast": "case-specific light and shadow structure",
            "texture": "photographer-specific detail and atmosphere",
        },
        "agent_guidance": [
            "先分析所选参考图的题材、光线和色彩关系是否适合目标照片。",
            "这类知识只定义参考分析方法，具体参数必须根据目标照片与参考图重新推理。",
        ],
    },
    "rgb_curve_method": {
        "style_family_name": "RGB曲线方法论",
        "role": "method_family",
        "parent_family": "editing_method",
        "active_for_photo_matching": False,
        "description": "围绕 RGB 曲线、万能曲线、胶片曲线的通用方法卡，不是单一视觉风格。",
        "suitable_scenes": ["需要曲线校色的照片", "胶片感尝试", "偏色修正"],
        "avoid_scenes": ["曲线已明显过度的照片"],
        "visual_features": {
            "tone": "curve-driven tone shaping",
            "color": "channel curve color separation",
            "contrast": "controlled by point curve",
            "texture": "case-specific",
        },
        "agent_guidance": [
            "把这类卡当成工具思路：先判断照片问题，再决定 RGB 曲线方向。",
            "曲线调整后必须复查肤色、中性色和高光暗部。",
        ],
    },
    "mask_local_retouch_method": {
        "style_family_name": "蒙版局部修图方法论",
        "role": "method_family",
        "parent_family": "editing_method",
        "active_for_photo_matching": False,
        "description": "蒙版、画笔、径向、渐变等局部调整方法，用于辅助视觉风格落地。",
        "suitable_scenes": ["需要主体提亮", "背景压暗", "局部色彩修正", "质感增强"],
        "avoid_scenes": ["全局调整已足够的照片"],
        "visual_features": {
            "tone": "local tone correction",
            "color": "local color cleanup",
            "contrast": "selective contrast",
            "texture": "localized detail control",
        },
        "agent_guidance": [
            "蒙版是执行手段，不应替代风格判断。",
            "每个局部调整都应记录作用对象和原因。",
        ],
    },
    "reference_color_matching_method": {
        "style_family_name": "综合仿色方法论",
        "role": "method_family",
        "parent_family": "editing_method",
        "active_for_photo_matching": False,
        "description": "大师仿色、参考图拆解和色彩底层逻辑的通用方法，不对应单一风格。",
        "suitable_scenes": ["有明确参考方向的照片", "摄影师风格拆解", "多案例总结"],
        "avoid_scenes": ["没有参考目标却强行套色"],
        "visual_features": {
            "tone": "reference-driven",
            "color": "match dominant reference palette",
            "contrast": "case-specific",
            "texture": "case-specific photographer texture",
        },
        "agent_guidance": [
            "先分析参考图的光线、色相和明暗关系，再生成参数。",
            "参考图思路只能迁移到题材和光线相近的照片。",
        ],
    },
    "tool_workflow_non_style": {
        "style_family_name": "工具流程非风格教程",
        "role": "workflow_reference",
        "parent_family": "editing_method",
        "active_for_photo_matching": False,
        "description": "插件、软件版本、AI 追色等工具流程内容，不作为照片风格候选。",
        "suitable_scenes": ["工具能力评估", "流程参考"],
        "avoid_scenes": ["直接作为调色风格匹配"],
        "visual_features": {
            "tone": "not a visual style",
            "color": "not a visual style",
            "contrast": "not a visual style",
            "texture": "not a visual style",
        },
        "agent_guidance": [
            "不要把工具体验卡直接匹配给照片。",
            "只在需要选择工作流或理解工具能力时参考。",
        ],
    },
    "non_tutorial_reference": {
        "style_family_name": "非教程参考素材",
        "role": "non_style_reference",
        "parent_family": "reference_only",
        "active_for_photo_matching": False,
        "description": "被来源列表收进来的非调色教程或转写无法抽取步骤的视频，仅保留为人工复核线索。",
        "suitable_scenes": ["人工复核", "来源清理"],
        "avoid_scenes": ["自动匹配照片", "自动生成调色计划"],
        "visual_features": {
            "tone": "insufficient tutorial evidence",
            "color": "insufficient tutorial evidence",
            "contrast": "insufficient tutorial evidence",
            "texture": "insufficient tutorial evidence",
        },
        "agent_guidance": [
            "不要用这类卡生成照片风格。",
            "需要人工确认它是否应从教程来源中移除，或改走视频抽帧视觉分析。",
        ],
    },
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_recipes(recipe_dir: Path) -> dict[str, dict[str, Any]]:
    recipes = {}
    for path in sorted(recipe_dir.glob("*.json")):
        payload = read_json(path)
        recipe_id = payload.get("recipe_id")
        if recipe_id:
            recipes[str(recipe_id)] = payload
    return recipes


def load_cards(card_dir: Path) -> list[dict[str, Any]]:
    cards = []
    for path in sorted(card_dir.glob("*.json")):
        payload = read_json(path)
        payload["_path"] = path
        cards.append(payload)
    return cards


def normalized_text(card: dict[str, Any], recipe: dict[str, Any] | None) -> str:
    parts: list[str] = [
        str(card.get("style_name", "")),
        str(card.get("source_video", {}).get("title", "")),
        " ".join(str(item) for item in card.get("tutorial_guidance", [])),
    ]
    evidence = card.get("evidence", {})
    parts.append(" ".join(str(item) for item in evidence.get("matched_keywords", [])))
    for step in evidence.get("representative_steps", []):
        if isinstance(step, dict):
            parts.append(str(step.get("text", "")))
    if recipe:
        parts.append(str(recipe.get("source", {}).get("title", "")))
        parts.append(str(recipe.get("transcript", {}).get("excerpt", ""))[:1200])
        extraction = recipe.get("extraction", {})
        parts.append(" ".join(str(item) for item in extraction.get("matched_keywords", [])))
    return "\n".join(parts).lower()


def contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in text for keyword in keywords)


def is_publishable_family(family_id: str) -> bool:
    return FAMILY_DEFINITIONS[family_id]["role"] in PUBLISHABLE_ROLES


def recipe_step_count(recipe: dict[str, Any] | None, card: dict[str, Any]) -> int:
    if recipe:
        steps = recipe.get("extraction", {}).get("steps", [])
        if isinstance(steps, list):
            return len(steps)
    return int(card.get("source_video", {}).get("step_count") or 0)


def classify_card(card: dict[str, Any], recipe: dict[str, Any] | None = None) -> str:
    text = normalized_text(card, recipe)
    title_parts = [str(card.get("source_video", {}).get("title", ""))]
    if recipe:
        title_parts.append(str(recipe.get("source", {}).get("title", "")))
    title = "\n".join(title_parts).lower()
    step_count = recipe_step_count(recipe, card)
    needs_review = bool((recipe or {}).get("quality", {}).get("needs_manual_review"))

    if step_count == 0 and (needs_review or contains_any(text, ["vlog", "自驾", "不是教程"])):
        return "non_tutorial_reference"
    if contains_any(title, ["工具篇", "ps2023", "beta", "ai追色", "像素蛋糕", "插件使用体验", "nik 9"]):
        return "tool_workflow_non_style"
    if contains_any(title, ["红绿蓝曲线", "rgb曲线", "rgb curve", "曲线调色法", "万能曲线", "曲线不会调"]):
        return "rgb_curve_method"
    if contains_any(title, ["黑白", "森山大道", "monochrome", "black and white"]):
        return "black_white_street_grain"
    if contains_any(title, ["风光", "航拍", "withluke", "户外探险", "史诗", "cuma cevik", "vincent crovi"]):
        if contains_any(title, ["蒙版", "蒙板", "径向", "渐变", "重塑光影", "层次"]):
            return "landscape_mask_light_rebuild"
        return "landscape_blue_green_epic"
    if contains_any(title, ["蒙版", "蒙板", "径向", "渐变", "画笔", "局部"]):
        if contains_any(title, ["人像修图", "质感人像", "魔法", "进阶", "lr“蒙板”", "lr蒙板"]):
            return "mask_local_retouch_method"
    if contains_any(title, ["底层逻辑", "仿色的底层", "建立个人风格", "色彩控制", "一个视频让你学会仿色"]):
        return "reference_color_matching_method"
    if contains_any(title, ["michael kagerer", "森林", "森系", "墨绿", "黄绿"]):
        return "forest_moss_green"
    if contains_any(title, ["梦幻", "粉紫", "动漫", "新海诚", "pastel", "anime", "henry"]):
        return "dreamy_pastel_anime"
    if contains_any(title, ["蓝调时刻", "旅拍夜景"]):
        return "blue_hour_travel_night"
    if contains_any(title, ["雨夜", "阴雨天", "rain night", "dimitri"]):
        return "rainy_cinematic_street"
    if contains_any(title, ["霓虹", "城市夜景", "都市", "夜景", "jungraphy"]):
        return "urban_neon_night"
    if contains_any(
        title,
        [
            "街拍",
            "扫街",
            "street",
            "电影感",
            "billy",
            "trystane",
            "tk_north",
            "monaris",
            "ryo konishi",
            "保井崇志",
            "kosnio",
        ],
    ):
        return "street_light_shadow_cinematic"
    if contains_any(title, ["低饱", "低饱和", "暗调", "暗黑", "品川力", "黑神话", "moody"]):
        return "dark_low_saturation_moody"
    if contains_any(title, ["家庭", "婚礼", "亲子", "生活照"]):
        return "warm_family_lifestyle"
    if contains_any(title, ["日落", "黄昏", "暖调", "暖系", "秋天", "秋季", "紫霞", "暖青", "sunset"]):
        return "warm_sunset_portrait"
    if contains_any(title, ["富士", "柯达", "cinestill", "5219", "经典负片", "nc滤镜", "胶片模拟"]):
        return "fuji_kodak_film_simulation"
    if contains_any(title, ["胶片灰", "日杂", "东京祐", "泽村洋兵", "大林直行"]):
        return "japanese_film_gray"
    if contains_any(title, ["胶片", "复古", "film"]):
        return "japanese_film_gray"
    if contains_any(title, ["韩系", "韩国", "hello nana", "grrrgom", "kai__photo", "小清新"]):
        return "korean_soft_portrait"
    if contains_any(title, ["逆光", "通透", "脸黑", "灰蒙蒙", "又黄又灰", "发黄", "硬光"]):
        return "japanese_transparent_backlight"
    if contains_any(title, ["青蓝", "蓝色少女", "故事感", "蓝调", "暗青"]):
        return "cyan_blue_story_portrait"
    if contains_any(title, ["日系", "干净", "清新", "樱花", "治愈"]):
        return "japanese_clean_portrait"

    current = card.get("style_family", {})
    current_id = current.get("style_id") if isinstance(current, dict) else ""
    if current_id in FAMILY_DEFINITIONS:
        return str(current_id)
    fallback_map = {
        "japanese_clean_portrait": "japanese_clean_portrait",
        "japanese_film_gray": "japanese_film_gray",
        "warm_portrait_sunset": "warm_sunset_portrait",
        "cinematic_street_night": "street_light_shadow_cinematic",
        "dark_low_saturation_moody": "dark_low_saturation_moody",
        "dreamy_pastel_anime": "dreamy_pastel_anime",
        "cyan_blue_story": "cyan_blue_story_portrait",
        "black_white_street_grain": "black_white_street_grain",
        "master_reference_texture": "photographer_reference_texture",
    }
    if current_id in fallback_map:
        return fallback_map[current_id]
    return "photographer_reference_texture"


def compact_title(title: str, limit: int = 54) -> str:
    cleaned = re.sub(r"【[^】]*】", "", title)
    cleaned = re.sub(r"（[^）]*(赠送|附|素材|预设|使用体验)[^）]*）", "", cleaned)
    cleaned = re.sub(r"\([^)]*(赠送|附|素材|预设|使用体验)[^)]*\)", "", cleaned)
    cleaned = re.sub(r"[｜|].*$", "", cleaned).strip(" 　-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) <= limit:
        return cleaned or title[:limit]
    return cleaned[: limit - 1].rstrip() + "…"


def update_card_family(card: dict[str, Any], family_id: str) -> dict[str, Any]:
    payload = {key: value for key, value in card.items() if key != "_path"}
    family = FAMILY_DEFINITIONS[family_id]
    previous_family = payload.get("coarse_style_family") or payload.get("style_family")
    if isinstance(previous_family, dict) and previous_family.get("style_id") != family_id:
        payload["coarse_style_family"] = previous_family
    payload["style_family"] = {
        "style_id": family_id,
        "style_name": family["style_family_name"],
        "path": str(DEFAULT_FAMILY_DIR / f"{family_id}.json"),
    }
    payload["style_lineage"] = {
        "layer1_family": family_id,
        "layer2_variant": payload.get("style_id"),
        "source_recipe": payload.get("source_recipe"),
    }
    payload["family_role"] = family["role"]
    payload["active_for_photo_matching"] = bool(family["active_for_photo_matching"])
    if family_id == "non_tutorial_reference":
        payload["status"] = "needs_manual_review"
        payload["review_notes"] = (
            str(payload.get("review_notes", "")).rstrip()
            + " This source currently has no extracted adjustment steps and is excluded from automatic photo matching."
        ).strip()
    elif family["role"] in {"method_family", "workflow_reference"}:
        payload.setdefault("status", "candidate")
        payload["review_notes"] = (
            str(payload.get("review_notes", "")).rstrip()
            + " This card is method/workflow guidance; use it as supporting reasoning rather than a direct visual style."
        ).strip()
    return payload


def build_family_payload(family_id: str, cards: list[dict[str, Any]]) -> dict[str, Any]:
    definition = FAMILY_DEFINITIONS[family_id]
    category_counts: Counter[str] = Counter()
    for card in cards:
        for category, count in card.get("evidence", {}).get("category_counts", {}).items():
            category_counts[str(category)] += int(count)

    operation_order: list[str] = []
    for category, _ in category_counts.most_common():
        operation = CATEGORY_OPERATION_MAP.get(category, category.replace(" ", "_"))
        if operation and operation not in operation_order:
            operation_order.append(operation)
    if not operation_order:
        operation_order = [
            "white_balance",
            "exposure_and_basic_tone",
            "tone_curve",
            "color_cleanup",
        ]
    if "final_review" not in operation_order:
        operation_order.append("final_review")

    visual_features = definition["visual_features"]
    payload = {
        "schema_version": "lumenflow.reusable_style_knowledge.v1",
        "style_id": family_id,
        "style_name": definition["style_family_name"],
        "status": "reusable",
        "knowledge_scope": "source_agnostic_semantic_family",
        "role": definition["role"],
        "parent_family": definition["parent_family"],
        "active_for_photo_matching": bool(
            definition["active_for_photo_matching"] and definition["role"] == "visual_style"
        ),
        "description": definition["description"],
        "suitable_scenes": definition["suitable_scenes"],
        "avoid_scenes": definition["avoid_scenes"],
        "visual_features": visual_features,
        "tone_guidance": {
            "overall": visual_features.get("tone", "adapt tone to the target photo"),
            "contrast": visual_features.get("contrast", "adapt contrast to the target photo"),
            "texture": visual_features.get("texture", "adapt texture to the target photo"),
        },
        "color_guidance": {
            "overall": visual_features.get("color", "adapt color to the target photo"),
            "subject_protection": "Preserve believable subject color and avoid destructive casts.",
        },
        "operation_order": operation_order[:8],
        "parameter_strategy": "agent_infers_per_photo",
        "adjustment_plan_guidance": {
            "schema_version": "lumenflow.adjustment_plan.v1",
            "rule": "Treat this knowledge as a reusable visual direction. Inspect the target photo before generating concrete values.",
            "variant_policy": "Generate one best variant by default; add alternates only when several directions genuinely fit.",
        },
        "agent_guidance": definition["agent_guidance"],
        "source_evidence": {
            "tutorial_count": len(cards),
            "category_counts": dict(sorted(category_counts.items())),
        },
        "raw_profile_role": "none",
        "raw_profiles": [],
    }
    validate_public_payload(payload)
    return payload


def validate_public_payload(payload: Any, path: str = "root") -> None:
    """Reject original-video identity or transcript evidence in tracked artifacts."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in FORBIDDEN_PUBLIC_KEYS:
                raise ValueError(f"forbidden public key at {path}.{key}")
            validate_public_payload(value, f"{path}.{key}")
        return
    if isinstance(payload, list):
        for index, value in enumerate(payload):
            validate_public_payload(value, f"{path}[{index}]")
        return
    if isinstance(payload, str):
        if re.search(r"https?://|\bBV[0-9A-Za-z]{6,}\b|bilibili_", payload, re.IGNORECASE):
            raise ValueError(f"source identity leaked into public payload at {path}")


def build_private_provenance(
    family_payloads: dict[str, dict[str, Any]],
    by_family: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    families: dict[str, Any] = {}
    for family_id in sorted(by_family):
        sources = []
        for card in sorted(by_family[family_id], key=lambda item: str(item.get("style_id", ""))):
            sources.append(
                {
                    "style_id": card.get("style_id"),
                    "source_recipe": card.get("source_recipe"),
                    "source_video": card.get("source_video", {}),
                }
            )
        families[family_id] = {
            "published": family_id in family_payloads,
            "public_path": (
                str(DEFAULT_FAMILY_DIR / f"{family_id}.json")
                if family_id in family_payloads
                else None
            ),
            "sources": sources,
        }
    return {
        "schema_version": "lumenflow.private_style_provenance.v1",
        "notice": "Private source map. Keep ignored by Git; public reusable knowledge must not depend on source identity.",
        "families": families,
    }


def write_tutorial_index(card_dir: Path, cards: list[dict[str, Any]]) -> Path:
    lines = [
        "# Tutorial Derived Style Cards",
        "",
        "Generated one private evidence card per successful tutorial recipe. Runtime retrieval uses only the source-clean knowledge under `knowledge/style_families/`.",
        "",
        "| style_id | layer1 family | role | active | language | steps | title |",
        "| --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for card in sorted(cards, key=lambda item: str(item.get("style_id", ""))):
        video = card.get("source_video", {})
        family = card.get("style_family", {})
        lines.append(
            "| `{}` | `{}` | {} | {} | {} | {} | {} |".format(
                card.get("style_id", ""),
                family.get("style_id", ""),
                card.get("family_role", ""),
                "yes" if card.get("active_for_photo_matching") else "no",
                video.get("language") or "",
                video.get("step_count") or 0,
                video.get("title") or "",
            )
        )
    index_path = card_dir / "index.md"
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index_path


def write_summary(summary_path: Path, family_payloads: dict[str, dict[str, Any]], cards: list[dict[str, Any]]) -> Path:
    active_count = sum(1 for card in cards if card.get("active_for_photo_matching"))
    lines = [
        "# Tutorial Recipe Style Summary",
        "",
        f"Generated from {len(cards)} successful tutorial recipes. The public layer has {len(family_payloads)} reusable source-agnostic knowledge cards under `knowledge/style_families/`; private video-level evidence remains under ignored paths for audit only.",
        "",
        f"Active for automatic photo matching: {active_count}. Method/workflow/reference cards remain available as supporting reasoning but are not direct visual styles.",
        "",
        "## Layer 1 Style Families",
        "",
        "| style_family_id | style family | role | active | source count | parent |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for family_id, payload in sorted(
        family_payloads.items(),
        key=lambda item: (
            -int(item[1].get("source_evidence", {}).get("tutorial_count", 0)),
            item[0],
        ),
    ):
        lines.append(
            "| `{}` | {} | {} | {} | {} | `{}` |".format(
                family_id,
                payload["style_name"],
                payload["role"],
                "yes" if payload["active_for_photo_matching"] else "no",
                payload["source_evidence"]["tutorial_count"],
                payload["parent_family"],
            )
        )

    lines.extend(
        [
            "",
            "## Video Mapping",
            "",
            "| recipe_id | language | segments | steps | layer1 family | role | active | video-level style card | video title |",
            "| --- | --- | ---: | ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for card in sorted(cards, key=lambda item: str(item.get("source_recipe", ""))):
        video = card.get("source_video", {})
        family = card.get("style_family", {})
        lines.append(
            "| `{}` | {} | {} | {} | `{}` | {} | {} | `{}` | {} |".format(
                card.get("source_recipe", ""),
                video.get("language") or "",
                video.get("segment_count") or 0,
                video.get("step_count") or 0,
                family.get("style_id", ""),
                card.get("family_role", ""),
                "yes" if card.get("active_for_photo_matching") else "no",
                card.get("style_id", ""),
                video.get("title") or "",
            )
        )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_path


def write_library_index(index_path: Path, family_payloads: dict[str, dict[str, Any]], cards: list[dict[str, Any]]) -> Path:
    role_counts = Counter(str(payload.get("role", "")) for payload in family_payloads.values())
    family_entries = []
    for family_id, payload in sorted(family_payloads.items()):
        family_entries.append(
            {
                "style_id": family_id,
                "style_name": payload["style_name"],
                "role": payload["role"],
                "active_for_photo_matching": payload["active_for_photo_matching"],
                "tutorial_count": payload["source_evidence"]["tutorial_count"],
                "path": str(DEFAULT_FAMILY_DIR / f"{family_id}.json"),
            }
        )
    inactive_families = [
        entry["style_id"] for entry in family_entries if not entry["active_for_photo_matching"]
    ]
    payload = {
        "schema_version": "lumenflow.style_library_index.v2",
        "knowledge_dir": str(DEFAULT_FAMILY_DIR),
        "styles": family_entries,
        "inactive_styles": inactive_families,
        "counts": {
            "reusable_knowledge_cards": len(family_payloads),
            "source_tutorials_merged": len(cards),
            "active_styles": sum(
                1 for payload in family_payloads.values() if payload.get("active_for_photo_matching")
            ),
            "inactive_styles": len(inactive_families),
            "by_role": dict(sorted(role_counts.items())),
        },
        "retrieval_policy": {
            "default": "Choose one reusable semantic style card by scene fit, visual intent, and avoid-scene constraints.",
            "parameter_policy": "The develop-photos agent must infer concrete parameters after inspecting the target photo; knowledge cards are not fixed presets.",
            "inactive_policy": "Knowledge with active_for_photo_matching=false is method/workflow/reference material and cannot be selected as the direct visual style.",
        },
    }
    validate_public_payload(payload)
    write_json(index_path, payload)
    return index_path


def build_layer(
    *,
    recipe_dir: Path = DEFAULT_RECIPE_DIR,
    card_dir: Path = DEFAULT_CARD_DIR,
    family_dir: Path = DEFAULT_FAMILY_DIR,
    index_path: Path = DEFAULT_INDEX_PATH,
    provenance_path: Path = DEFAULT_PROVENANCE_PATH,
    summary_path: Path = DEFAULT_SUMMARY_PATH,
) -> dict[str, Any]:
    recipes = load_recipes(recipe_dir)
    cards = load_cards(card_dir)
    updated_cards: list[dict[str, Any]] = []
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for card in cards:
        recipe_id = str(card.get("source_recipe", ""))
        recipe = recipes.get(recipe_id)
        family_id = classify_card(card, recipe)
        updated = update_card_family(card, family_id)
        evidence = updated.setdefault("evidence", {})
        if not evidence.get("category_counts") and recipe:
            categories = Counter(
                str(step.get("category", "unknown"))
                for step in recipe.get("extraction", {}).get("steps", [])
            )
            evidence["category_counts"] = dict(sorted(categories.items()))
        write_json(Path(card["_path"]), updated)
        updated_cards.append(updated)
        by_family[family_id].append(updated)

    family_dir.mkdir(parents=True, exist_ok=True)
    family_payloads: dict[str, dict[str, Any]] = {}
    stale_files = {path for path in family_dir.glob("*.json")}
    for family_id in sorted(by_family):
        if not is_publishable_family(family_id):
            continue
        payload = build_family_payload(family_id, by_family[family_id])
        family_payloads[family_id] = payload
        path = family_dir / f"{family_id}.json"
        write_json(path, payload)
        stale_files.discard(path)
    for stale_file in stale_files:
        stale_file.unlink()

    write_library_index(index_path, family_payloads, updated_cards)
    write_json(provenance_path, build_private_provenance(family_payloads, by_family))
    write_tutorial_index(card_dir, updated_cards)
    write_summary(summary_path, family_payloads, updated_cards)

    return {
        "style_families": len(family_payloads),
        "semantic_groups": len(by_family),
        "reusable_knowledge_cards": len(family_payloads),
        "active_styles": sum(
            1 for payload in family_payloads.values() if payload.get("active_for_photo_matching")
        ),
        "inactive_styles": sum(
            1 for payload in family_payloads.values() if not payload.get("active_for_photo_matching")
        ),
        "private_only_groups": sum(
            1 for family_id in by_family if not is_publishable_family(family_id)
        ),
        "tutorial_variants": len(updated_cards),
        "active_tutorial_variants": sum(1 for card in updated_cards if card.get("active_for_photo_matching")),
        "inactive_tutorial_variants": sum(1 for card in updated_cards if not card.get("active_for_photo_matching")),
        "family_counts": {
            family_id: len(cards_for_family)
            for family_id, cards_for_family in sorted(by_family.items())
        },
        "index_path": str(index_path),
        "family_dir": str(family_dir),
        "provenance_path": str(provenance_path),
        "summary_path": str(summary_path),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe-dir", type=Path, default=DEFAULT_RECIPE_DIR)
    parser.add_argument("--card-dir", type=Path, default=DEFAULT_CARD_DIR)
    parser.add_argument("--family-dir", type=Path, default=DEFAULT_FAMILY_DIR)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX_PATH)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = build_layer(
        recipe_dir=args.recipe_dir,
        card_dir=args.card_dir,
        family_dir=args.family_dir,
        index_path=args.index,
        provenance_path=args.provenance,
        summary_path=args.summary,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
