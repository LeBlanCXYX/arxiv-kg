import json
import os
import sys
from openai import OpenAI

from config import API_KEY, BASE_URL, MODEL_NAME, is_api_configured

INPUT_FILE = "result.json"  # 默认图谱文件，可通过命令行参数覆盖

def load_knowledge_graph(path=None):
    """加载知识图谱 JSON，path 为空时使用 INPUT_FILE。"""
    path = path or INPUT_FILE
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _triple_to_fact(triple):
    """将单条三元组转为自然语言事实；兼容 head/tail 与 subject/object。"""
    head = triple.get("head") or triple.get("subject")
    tail = triple.get("tail") or triple.get("object")
    rel = triple.get("relation", "")
    if not head or not tail:
        return None
    if rel == "proposed_model":
        return f"{head} 提出了模型 {tail}。"
    if rel == "baseline_model":
        return f"{head} 对比的基线模型是 {tail}。"
    if rel == "evaluated_on":
        return f"{head} 在数据集 {tail} 上进行了评估。"
    if rel == "uses_metric":
        return f"{head} 使用的评估指标是 {tail}。"
    if rel == "author_of":
        return f"{head} 是论文《{tail}》的作者。"
    if rel == "cites":
        return f"{head} 引用了 {tail}。"
    return f"{head} 的 {rel} 是 {tail}。" if rel else None


def graph_rag_qa(user_query, kg_data):
    """
    实现一个简单的 Graph RAG (图谱增强检索)
    1. 将图谱的三元组转化为自然语言上下文
    2. 让大模型仅根据这些上下文回答问题，防止幻觉
    """
    if not is_api_configured():
        return "❌ 请配置 API Key：复制 config_local.py.example 为 config_local.py 并填入 Key，或设置环境变量 OPENAI_API_KEY。"
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    # 1. 知识图谱扁平化 (Flattening)
    paper_meta = kg_data.get("paper_metadata", {})
    paper_title = paper_meta.get("title", "")
    facts = [f"论文《{paper_title}》的元数据: {json.dumps(paper_meta, ensure_ascii=False)}"]

    for triple in kg_data.get("knowledge_graph", {}).get("triples", []):
        fact = _triple_to_fact(triple)
        if fact:
            facts.append(fact)

    context_str = "\n".join(facts)
    system_prompt = f"""你是一个基于知识图谱的智能问答助手。仅根据我提供的【已知知识图谱事实】回答用户问题。

【已知知识图谱事实】：
{context_str}

要求：若答案在事实中请准确回答；若不在请直接说“知识图谱中未包含此信息”，严禁编造。回答简洁、专业。"""

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query},
            ],
            temperature=0.1,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ 调用失败: {e}"

if __name__ == "__main__":
    input_path = (sys.argv[1] if len(sys.argv) > 1 else None) or INPUT_FILE
    kg_data = load_knowledge_graph(input_path)

    if not kg_data:
        print(f"❌ 找不到文件: {input_path}，请先生成图谱 (如 result.json 或 top_citations_kg_*.json)")
    else:
        title = kg_data.get("paper_metadata", {}).get("title", "未知")
        print("==============================================")
        print(f"🤖 知识图谱 QA 已启动 (基于: {title})")
        print("可问：'这篇论文提出了什么模型？'、'使用了哪个数据集？'、'引用了哪些论文？'")
        print("输入 'exit' 退出")
        print("==============================================")

        while True:
            try:
                query = input("\n🙋 请提问: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if query.lower() == "exit":
                break
            if not query:
                continue
            print("Thinking...")
            answer = graph_rag_qa(query, kg_data)
            print(f"🤖 回答: {answer}")