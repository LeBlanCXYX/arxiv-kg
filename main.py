import arxiv
import json
import os
import requests
import time
from openai import OpenAI

from config import API_KEY, BASE_URL, MODEL_NAME, is_api_configured
def fetch_citations_via_semantic_scholar(arxiv_id):
    """
    通过 Semantic Scholar API 获取引用关系
    input: arxiv_id (e.g., "1706.03762")
    output: 引用列表 (references) 和 被引列表 (citations)
    """
    print(f"[*] 正在通过 Semantic Scholar 查询引用关系: {arxiv_id} ...")
    
    # Semantic Scholar 支持直接用 ArXiv ID 查询
    # fields 参数指定我们需要标题、年份和论文ID
    url = f"https://api.semanticscholar.org/graph/v1/paper/ARXIV:{arxiv_id}?fields=title,year,references.title,references.paperId,citations.title,citations.paperId"
    
    try:
        # ⚠️ 注意：如果没有 API Key，S2 限制每秒 1-2 次请求。
        # 作业演示不需要 Key，但请不要并发太快。
        r = requests.get(url, timeout=10)
        
        if r.status_code == 200:
            data = r.json()
            
            # 提取“它引用了谁” (References)
            refs = []
            if data.get('references'):
                # 我们只取前 5 个作为演示，防止图谱爆炸
                for item in data['references'][:5]: 
                    if item.get('title'):
                        refs.append({
                            "name": item['title'],
                            "type": "AIPaper", # 这里的类型也是论文
                            "relation": "cites" # 关系：引用
                        })
            
            # 提取“谁引用了它” (Citations)
            cited_by = []
            if data.get('citations'):
                # 只取前 5 个最有名的引用者
                for item in data['citations'][:5]:
                    if item.get('title'):
                        cited_by.append({
                            "name": item['title'],
                            "type": "AIPaper",
                            "relation": "cited_by" # 关系：被引用
                        })
            
            print(f"✅ 发现 {len(data.get('references', []))} 条参考文献，{len(data.get('citations', []))} 条被引记录。")
            return refs + cited_by
            
        elif r.status_code == 404:
            print("❌ Semantic Scholar 未收录此 ArXiv ID (可能是刚发的论文)")
            return []
        else:
            print(f"⚠️ API 请求失败: {r.status_code}")
            return []
            
    except Exception as e:
        print(f"❌ 网络错误: {e}")
        return []
    
def fetch_arxiv_paper(paper_id):
    """
    步骤 1: 使用 ArXiv API 获取论文的元数据 (标题, 摘要, 作者, 时间)
    这是结构化数据的来源。
    """
    print(f"[*] 正在下载 ArXiv 论文元数据: {paper_id} ...")
    client = arxiv.Client()
    search = arxiv.Search(id_list=[paper_id])
    
    try:
        paper = next(client.results(search))
        paper_info = {
            "title": paper.title,
            "abstract": paper.summary,
            "published_date": paper.published.strftime("%Y-%m-%d"),
            "pdf_url": paper.pdf_url,
            "authors": [author.name for author in paper.authors]
        }
        print(f"✅ 成功获取: {paper.title}")
        return paper_info
    except StopIteration:
        print("❌ 未找到该 ID 的论文，请检查 ID 是否正确。")
        return None
    except Exception as e:
        print(f"❌ 网络或解析错误: {e}")
        return None

def extract_knowledge_with_llm(paper_info):
    """
    步骤 2: 调用大模型 API 进行【深度抽取】
    这里是作业得分的核心：利用 NLP 理解文本，提取出正则无法匹配的 'baseline_model' 等复杂关系。
    """
    print("[*] 正在调用大模型进行深度抽取 (Schema Mapping)...")
    
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    # 构造 Prompt：严格遵循我们定义的 cnSchema 扩展结构
    system_prompt = """
    你是一个构建人工智能学术图谱的专家。你的任务是从论文摘要中提取实体和关系。
    
    请严格遵循以下 Schema 定义进行抽取：
    1. 实体类型: 
       - AIPaper (论文本身)
       - AIModel (模型/架构, 如 Transformer, ResNet)
       - Dataset (数据集, 如 ImageNet)
       - Metric (指标, 如 BLEU)
    
    2. 关系类型 (Triples):
       - (AIPaper) -> [proposed_model] -> (AIModel): 论文提出的新模型
       - (AIPaper) -> [baseline_model] -> (AIModel): 论文对比的基线模型 (通常出现在 "outperforms", "unlike" 等语境)
       - (AIPaper) -> [evaluated_on] -> (Dataset): 实验用的数据集
       - (AIPaper) -> [uses_metric] -> (Metric): 使用的评估指标
       - (AIModel) -> [parameter_count] -> (String): 模型参数量 (如果提到)

    要求：triples 必须使用 "head" 和 "tail" 字段，其值为实体名称（论文标题、模型名、数据集名等），不要用 E1、E2 等 ID。
    请直接输出标准的 JSON 格式，不要包含 Markdown 标记。格式如下：
    {
        "entities": [{"name": "...", "type": "..."}],
        "triples": [{"head": "...", "relation": "...", "tail": "..."}]
    }
    """

    user_prompt = f"""
    论文标题: {paper_info['title']}
    论文摘要: {paper_info['abstract']}
    
    请开始抽取：
    """

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        result = response.choices[0].message.content
        return json.loads(result)
    except Exception as e:
        print(f"❌ LLM 调用失败: {e}")
        return None

def save_result(paper_info, kg_data, output_file="result.json"):
    """
    步骤 3: 结果整合
    将元数据（结构化）和抽取数据（非结构化）合并，生成最终作业提交文件。
    """
    # 构造符合 cnSchema 的最终 JSON 对象
    final_output = {
        "paper_metadata": paper_info,
        "knowledge_graph": kg_data
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)
    print(f"✅ 结果已保存至: {output_file}")
    print("--------------------------------------------------")
    print(json.dumps(final_output, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    import sys
    if not is_api_configured():
        print("❌ 请先配置 API Key：复制 config_local.py.example 为 config_local.py 并填入 Key，或设置环境变量 OPENAI_API_KEY。")
        sys.exit(1)
    target_id = "1706.03762"  # Transformer
    # 1. 获取 ArXiv 基础信息
    paper_data = fetch_arxiv_paper(target_id)
    
    if paper_data:
        # 2. LLM 深度抽取 (内容抽取)
        kg_result = extract_knowledge_with_llm(paper_data)
        
        # 3. [新增] Semantic Scholar 引用抽取 (网络结构抽取)
        citation_triples = fetch_citations_via_semantic_scholar(target_id)
        
        if kg_result:
            # === 将引用数据合并到你的 JSON ===
            
            # 1. 把新的实体（引用论文）加到 entities 列表
            existing_names = set(e['name'] for e in kg_result['entities'])
            for item in citation_triples:
                if item['name'] not in existing_names:
                    kg_result['entities'].append({
                        "name": item['name'],
                        "type": "AIPaper"
                    })
                    existing_names.add(item['name'])
            
            # 2. 把新的关系（cites/cited_by）加到 triples 列表
            current_paper_title = paper_data['title']
            for item in citation_triples:
                if item['relation'] == 'cites':
                    # 主论文 -> 引用 -> 参考文献
                    kg_result['triples'].append({
                        "head": current_paper_title,
                        "relation": "cites",
                        "tail": item['name']
                    })
                elif item['relation'] == 'cited_by':
                    # 其他论文 -> 引用 -> 主论文
                    kg_result['triples'].append({
                        "head": item['name'],
                        "relation": "cites",
                        "tail": current_paper_title
                    })

            # 4. 保存最终结果
            save_result(paper_data, kg_result)