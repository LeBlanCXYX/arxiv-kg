"""
递归引用知识图谱 (Recursive Citations KG)
在 top_citations_kg 基础上增加递归深度：按层展开每篇论文的 top-k 引用与被引，直到达到指定深度。
不修改现有文件，仅复用 top_citations_kg 中的拉取与可视化逻辑。

用法:
  python recursive_citations_kg.py <arxiv_id> -k <top_k> -d <depth>
  python recursive_citations_kg.py 1706.03762 -k 3 -d 2 --llm
"""

import json
import os
import argparse
from collections import deque

# 复用 top_citations_kg 的拉取、元数据补全与可视化
from top_citations_kg import (
    fetch_arxiv_paper,
    fetch_related_papers_via_semantic_scholar,
    batch_ensure_metadata,
    generate_html,
)
from top_citations_kg import extract_knowledge_with_llm  # 可选 --llm


def run_recursive_citations(arxiv_id, top_k=5, depth=2, run_llm=False):
    """
    递归展开引用/被引：每层对当前论文取 top_k 引用 + top_k 被引，直到深度 depth。
    depth=1：仅种子论文 + 其 top_k 引用/被引（等价于不递归）。
    depth=2：再展开上述每篇的 top_k 引用/被引，不再递归。
    """
    print("\n" + "=" * 60)
    print("🚀 递归引用知识图谱 (Recursive Citations KG)")
    print("=" * 60)
    print(f"   ArXiv ID: {arxiv_id}, Top K: {top_k}, 深度: {depth}")

    seed = fetch_arxiv_paper(arxiv_id)
    if not seed:
        return False

    papers_by_title = {seed["title"]: seed}
    edges = []  # (head_title, tail_title)
    expanded_arxiv = set()
    to_expand = deque([(arxiv_id, 0)])  # (arxiv_id, level)

    while to_expand:
        aid, level = to_expand.popleft()
        if aid in expanded_arxiv:
            continue
        expanded_arxiv.add(aid)
        paper = fetch_arxiv_paper(aid) if aid else None
        if not paper:
            continue
        papers_by_title[paper["title"]] = paper

        if level >= depth:
            continue
        rel = fetch_related_papers_via_semantic_scholar(aid, top_n=top_k)
        for r in rel["references"]:
            if r.get("title"):
                papers_by_title[r["title"]] = r
                edges.append((paper["title"], r["title"]))
                rid = r.get("arxiv_id")
                if rid and rid not in expanded_arxiv:
                    to_expand.append((rid, level + 1))
        for c in rel["citations"]:
            if c.get("title"):
                papers_by_title[c["title"]] = c
                edges.append((c["title"], paper["title"]))
                cid = c.get("arxiv_id")
                if cid and cid not in expanded_arxiv:
                    to_expand.append((cid, level + 1))

    all_papers = list(papers_by_title.values())
    batch_ensure_metadata(all_papers)

    seen_names = set()
    entities = []
    triples = []

    for p in all_papers:
        name = p.get("title") or ""
        if name and name not in seen_names:
            entities.append({
                "name": name,
                "type": "AIPaper",
                "arxiv_id": p.get("arxiv_id") or p.get("id", ""),
            })
            seen_names.add(name)
    for p in all_papers:
        for a in p.get("authors", []):
            if a and a not in seen_names:
                entities.append({"name": a, "type": "Researcher"})
                seen_names.add(a)

    for p in all_papers:
        for a in p.get("authors", []):
            if a and p.get("title"):
                triples.append({"head": a, "relation": "author_of", "tail": p["title"]})
    for h, t in edges:
        if h and t:
            triples.append({"head": h, "relation": "cites", "tail": t})

    if run_llm:
        for p in all_papers:
            llm_data = extract_knowledge_with_llm(p)
            id_to_name = {}
            for e in llm_data.get("entities", []):
                n = e.get("name")
                if n:
                    if n not in seen_names:
                        entities.append({"name": n, "type": e.get("type", "AIPaper")})
                        seen_names.add(n)
                    if e.get("id"):
                        id_to_name[e["id"]] = n
                    id_to_name[n] = n
            for t in llm_data.get("triples", []):
                head = t.get("head") or t.get("subject")
                tail = t.get("tail") or t.get("object")
                if not head or not tail:
                    continue
                head = id_to_name.get(head, head)
                tail = id_to_name.get(tail, tail)
                triples.append({"head": head, "relation": t.get("relation", ""), "tail": tail})

    def _paper_meta(p):
        return {
            "title": p.get("title", ""),
            "arxiv_id": p.get("arxiv_id", ""),
            "abstract": p.get("abstract", ""),
            "authors": p.get("authors", []),
            "published_date": p.get("published_date", ""),
            "pdf_url": p.get("pdf_url", ""),
            "citation_count": p.get("citation_count"),
            "year": p.get("year"),
        }

    ref_count = sum(1 for h, t in edges if h == seed["title"])
    cite_count = sum(1 for h, t in edges if t == seed["title"])
    output_data = {
        "paper_metadata": seed,
        "related_papers_count": {"references": ref_count, "citations": cite_count},
        "related_papers": [_paper_meta(p) for p in all_papers if p["title"] != seed["title"]],
        "top_k": top_k,
        "depth": depth,
        "knowledge_graph": {"entities": entities, "triples": triples},
    }

    base_name = f"recursive_kg_{arxiv_id}_k{top_k}_d{depth}"
    json_path = f"{base_name}.json"
    html_path = f"{base_name}.html"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ JSON 已保存: {json_path}")

    generate_html(json_path, html_path, output_data)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="递归展开论文的引用/被引：每层取 top-k 引用与被引，共 depth 层"
    )
    parser.add_argument("arxiv_id", nargs="?", default="1706.03762", help="种子论文 ArXiv ID")
    parser.add_argument("-k", "--top", type=int, default=5, help="每层引用/被引各取前 K 篇 (默认 5)")
    parser.add_argument("-d", "--depth", type=int, default=2, help="递归深度 (默认 2：本论文 + 一层邻接 + 二层邻接)")
    parser.add_argument("--llm", action="store_true", help="是否进行 LLM 深度抽取")
    args = parser.parse_args()
    run_recursive_citations(args.arxiv_id, top_k=args.top, depth=args.depth, run_llm=args.llm)