"""
基于 classes.json 的实体类型约束与扩展。
知识图谱中的实体类型必须来源于 classes.json 中定义的类，或通过映射表映射到该类体系。
"""

import json
import os
from typing import Set, List, Dict, Any, Optional

# 默认 classes.json 路径（与脚本同目录）
DEFAULT_CLASSES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "classes.json")

# 项目内使用的类型名 -> classes.json 中的规范类型名
TYPE_ALIASES = {
    "AIPaper": "Thesis",           # 论文 -> Schema 中的 Thesis（论文）
    "Researcher": "Person",        # 研究者 -> Person
    "AIModel": "SoftwareApplication",  # 模型 -> 软件应用
    "Metric": "CreativeWork",     # 指标 -> 创作（schema 中无 DefinedTerm 时用 CreativeWork）
}

# 若 LLM 返回的类型不在 schema 中，则映射到以下默认类型（需在 classes.json 中存在）
DEFAULT_TYPE = "CreativeWork"


def _collect_type_names(node: Dict[str, Any], out: Set[str]) -> None:
    """递归收集节点及其子节点的 name（非空）。"""
    name = (node.get("name") or "").strip()
    if name:
        out.add(name)
    for child in node.get("children", []):
        _collect_type_names(child, out)


def load_classes(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """加载 classes.json，返回根节点列表。"""
    path = path or DEFAULT_CLASSES_PATH
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_all_type_names(classes: Optional[List[Dict[str, Any]]] = None, path: Optional[str] = None) -> Set[str]:
    """
    获取 classes.json 中所有类型名（非空）的集合。
    若未传入 classes 则从 path 加载（默认 DEFAULT_CLASSES_PATH）。
    """
    if classes is None:
        classes = load_classes(path)
    out: Set[str] = set()
    for root in classes:
        _collect_type_names(root, out)
    return out


def normalize_entity_type(
    type_name: str,
    allowed: Optional[Set[str]] = None,
    aliases: Optional[Dict[str, str]] = None,
    default: str = DEFAULT_TYPE,
) -> str:
    """
    将实体类型规范化为 classes.json 中的类型。
    - 若 type_name 已在 allowed 中，直接返回；
    - 否则若在 aliases 中有映射且映射后在 allowed 中，返回映射值；
    - 否则返回 default（须在 allowed 中）。
    """
    if not (type_name or "").strip():
        return default
    type_name = (type_name or "").strip()
    if allowed is None:
        allowed = get_all_type_names()
    aliases = aliases or TYPE_ALIASES
    if type_name in allowed:
        return type_name
    mapped = aliases.get(type_name)
    if mapped and mapped in allowed:
        return mapped
    if default in allowed:
        return default
    # 若 default 不在 allowed 中，返回 allowed 中任意一个（优先 CreativeWork）
    for fallback in ("CreativeWork", "Person", "Article"):
        if fallback in allowed:
            return fallback
    return list(allowed)[0] if allowed else type_name


def get_categories_for_entities(
    entity_types: List[str],
    allowed: Optional[Set[str]] = None,
    aliases: Optional[Dict[str, str]] = None,
) -> List[str]:
    """
    根据实体中出现的类型，得到规范化的类型列表（用于可视化 categories）。
    仅包含在 classes.json 中存在的类型，且去重、有序。
    """
    if allowed is None:
        allowed = get_all_type_names()
    aliases = aliases or TYPE_ALIASES
    seen: Set[str] = set()
    result: List[str] = []
    for t in entity_types:
        norm = normalize_entity_type(t, allowed=allowed, aliases=aliases)
        if norm and norm not in seen:
            seen.add(norm)
            result.append(norm)
    return result


def get_types_for_llm_prompt(allowed: Optional[Set[str]] = None) -> str:
    """
    返回给 LLM 的实体类型说明：仅使用 classes.json 中与论文/学术相关的类型子集。
    用于 extract_knowledge_with_llm 的 system_prompt。
    """
    if allowed is None:
        allowed = get_all_type_names()
    # 与论文、人物、模型、数据集相关的 schema 类型
    relevant = [
        "Thesis", "Article", "CreativeWork", "Person",
        "Dataset", "SoftwareApplication", "TechArticle", "Report",
    ]
    subset = [t for t in relevant if t in allowed]
    if not subset:
        subset = sorted(allowed)[:15]  # 回退：取前 15 个
    return ", ".join(subset)
