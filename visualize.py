import argparse
import json
import os

from class_schema import get_all_type_names, normalize_entity_type, get_categories_for_entities

# ================= 配置区域 =================
INPUT_FILE = "final_kg_5_papers.json"
OUTPUT_FILE = "knowledge_graph.html"
# ===========================================
ALLOWED_TYPES = get_all_type_names()


def generate_html(json_file, output_file=None):
    """
    根据知识图谱 JSON 生成 ECharts 力导向图 HTML。
    增强版 V2：
    1. 复选框直接控制类别显示/隐藏 (Legend Toggle)。
    2. 搜索功能支持节点名与关系名，并在当前视野中高亮。
    """
    if not os.path.exists(json_file):
        print(f"❌ 错误：找不到文件 {json_file}")
        return None

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    paper_meta = data.get("paper_metadata", {})
    kg = data.get("knowledge_graph", {})
    entities = kg.get("entities", [])
    triples = kg.get("triples", [])

    # 1. 处理类别 (Categories)
    raw_types = [e.get("type", "Thesis") for e in entities]
    type_list = get_categories_for_entities(raw_types)
    category_map = {t: i for i, t in enumerate(type_list)}
    categories = [{"name": t} for t in type_list]

    # 2. 处理节点 (Nodes)
    name_to_entity = {}
    for e in entities:
        name = (e.get("name") or "").strip()
        if name and name not in name_to_entity:
            name_to_entity[name] = e
    
    echarts_nodes = []
    seen_nodes = set()
    for name, e in name_to_entity.items():
        etype = normalize_entity_type(e.get("type", "Thesis"), allowed=ALLOWED_TYPES)
        echarts_nodes.append({
            "name": name,
            "category": category_map.get(etype, 0),
            "symbolSize": 50 if etype in ("Thesis", "Article", "CreativeWork") else 25,
            "draggable": True,
            "value": etype,
            "label": {"show": True} 
        })
        seen_nodes.add(name)

    # 补充 Researcher 类别
    person_type = normalize_entity_type("Researcher", allowed=ALLOWED_TYPES)
    if person_type not in category_map:
        categories.append({"name": person_type})
        category_map[person_type] = len(categories) - 1
    
    # 补充作者节点
    for author in paper_meta.get("authors", []):
        author = (author or "").strip()
        if author and author not in seen_nodes:
            echarts_nodes.append({
                "name": author,
                "category": category_map[person_type],
                "symbolSize": 20,
                "value": person_type,
            })
            seen_nodes.add(author)

    # 3. 处理连线 (Links)
    echarts_links = []
    title = paper_meta.get("title")
    if title and title in seen_nodes:
        for author in paper_meta.get("authors", []):
            if author and author in seen_nodes:
                echarts_links.append({"source": author, "target": title, "value": "author"})

    for t in triples:
        head = (t.get("head") or t.get("subject") or "").strip()
        tail = (t.get("tail") or t.get("object") or "").strip()
        if head and tail and head in seen_nodes and tail in seen_nodes:
            echarts_links.append({
                "source": head,
                "target": tail,
                "value": t.get("relation", ""),
            })

    # 4. 生成 HTML 模板
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>AI Knowledge Graph - {paper_meta.get('title', 'Demo')}</title>
        <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
        <style>
            body {{ margin: 0; padding: 0; background-color: #f4f4f4; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }}
            #main {{ width: 100vw; height: 100vh; }}
            
            /* 标题面板 */
            .header {{ 
                position: absolute; top: 20px; left: 20px; z-index: 999; 
                background: rgba(255,255,255,0.95); padding: 15px; border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1); max-width: 300px;
            }}
            .header h2 {{ margin: 0 0 10px 0; font-size: 18px; color: #333; }}
            .header p {{ margin: 5px 0; font-size: 12px; color: #666; }}

            /* 搜索控制面板 */
            .search-panel {{
                position: absolute; top: 20px; right: 20px; z-index: 999;
                background: rgba(255,255,255,0.95); padding: 20px; border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1); width: 280px;
            }}
            .search-panel h3 {{ margin: 0 0 15px 0; font-size: 16px; color: #333; border-bottom: 1px solid #eee; padding-bottom: 10px; }}
            
            .form-group {{ margin-bottom: 15px; }}
            .form-group label {{ display: block; margin-bottom: 5px; font-size: 12px; font-weight: bold; color: #555; }}
            
            input[type="text"] {{
                width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px;
                box-sizing: border-box; font-size: 14px;
            }}
            
            .checkbox-group {{
                max-height: 200px; overflow-y: auto; border: 1px solid #eee; padding: 5px; border-radius: 4px;
                background: #fff;
            }}
            .checkbox-item {{ display: flex; align-items: center; margin-bottom: 5px; font-size: 13px; cursor: pointer; }}
            .checkbox-item:hover {{ background-color: #f9f9f9; }}
            .checkbox-item input {{ margin-right: 8px; cursor: pointer; }}
            .checkbox-item span {{ cursor: pointer; }}
            
            .btn-group {{ display: flex; gap: 10px; margin-top: 15px; }}
            button {{
                flex: 1; padding: 8px; border: none; border-radius: 4px; cursor: pointer;
                font-size: 13px; transition: background 0.2s;
            }}
            .btn-search {{ background: #007bff; color: white; }}
            .btn-search:hover {{ background: #0056b3; }}
            .btn-reset {{ background: #6c757d; color: white; }}
            .btn-reset:hover {{ background: #545b62; }}

            #search-status {{ margin-top: 10px; font-size: 12px; color: #e74c3c; font-weight: bold; min-height: 16px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>📄 {paper_meta.get('title', 'Paper KG')}</h2>
            <p><strong>Published:</strong> {paper_meta.get('published_date', '')}</p>
            <p><strong>Entities:</strong> {len(echarts_nodes)} | <strong>Relations:</strong> {len(echarts_links)}</p>
        </div>

        <div class="search-panel">
            <h3>🛠️ 控制面板</h3>
            
            <div class="form-group">
                <label>🔍 搜索 (节点名/关系):</label>
                <input type="text" id="searchInput" placeholder="Enter text..." onkeydown="if(event.keyCode==13) performSearch()">
            </div>
            
            <div class="form-group">
                <label>👁️ 类别可见性 (Visibility):</label>
                <div class="checkbox-group" id="categoryCheckboxes">
                    </div>
            </div>

            <div class="btn-group">
                <button class="btn-search" onclick="performSearch()">搜索 & 高亮</button>
                <button class="btn-reset" onclick="resetView()">重置视图</button>
            </div>
            <div id="search-status"></div>
        </div>

        <div id="main"></div>

        <script type="text/javascript">
            var chartDom = document.getElementById('main');
            var myChart = echarts.init(chartDom);
            
            var graphNodes = {json.dumps(echarts_nodes)};
            var graphLinks = {json.dumps(echarts_links)};
            var graphCategories = {json.dumps(categories)};

            // 初始化所有类别为选中状态
            var selectedCategories = {{}};
            graphCategories.forEach(function(c) {{ selectedCategories[c.name] = true; }});

            var option = {{
                title: {{ text: '' }},
                tooltip: {{
                    formatter: function(params) {{
                        if (params.dataType === 'node') {{
                            return '<strong>' + params.name + '</strong><br/>Type: ' + params.data.value;
                        }}
                        return params.data.source + ' > ' + params.data.value + ' > ' + params.data.target;
                    }}
                }},
                // 图例配置：show: false 隐藏自带图例，但保留功能供我们调用
                legend: [{{
                    show: false, 
                    data: graphCategories.map(function (a) {{ return a.name; }}),
                    selected: selectedCategories
                }}],
                series: [
                    {{
                        name: 'Knowledge Graph',
                        type: 'graph',
                        layout: 'force',
                        data: graphNodes,
                        links: graphLinks,
                        categories: graphCategories,
                        roam: true,
                        label: {{
                            show: true,
                            position: 'right',
                            formatter: '{{b}}'
                        }},
                        edgeLabel: {{
                            show: true,
                            fontSize: 10,
                            formatter: '{{c}}',
                            color: '#ccc'
                        }},
                        edgeSymbol: ['none', 'arrow'],
                        edgeSymbolSize: 10,
                        lineStyle: {{
                            color: 'source',
                            curveness: 0.3,
                            width: 1.5
                        }},
                        force: {{
                            repulsion: 800,
                            edgeLength: 150,
                            gravity: 0.1
                        }},
                        emphasis: {{
                            focus: 'adjacency',
                            lineStyle: {{ width: 4 }}
                        }},
                        select: {{
                            itemStyle: {{ borderColor: '#000', borderWidth: 2 }}
                        }}
                    }}
                ]
            }};

            myChart.setOption(option);
            
            window.addEventListener('resize', function() {{ myChart.resize(); }});

            // ==================== 逻辑实现 ====================
            
            var checkboxContainer = document.getElementById('categoryCheckboxes');

            // 1. 动态生成复选框，并绑定 Legend 开关事件
            graphCategories.forEach(function(cat, index) {{
                var div = document.createElement('div');
                div.className = 'checkbox-item';
                
                var input = document.createElement('input');
                input.type = 'checkbox';
                input.id = 'cat_' + index;
                input.value = cat.name;
                input.checked = true; // 默认全选
                
                // 核心逻辑：复选框 Change -> ECharts Legend Select/UnSelect
                input.addEventListener('change', function() {{
                    var name = this.value;
                    var type = this.checked ? 'legendSelect' : 'legendUnSelect';
                    
                    // 触发 ECharts 行为，节点会自动消失/出现
                    myChart.dispatchAction({{
                        type: type,
                        name: name
                    }});
                    
                    // 更新内部状态
                    selectedCategories[name] = this.checked;
                }});

                var label = document.createElement('span');
                label.innerText = cat.name;
                label.onclick = function() {{ input.click(); }}; // 点击文字也触发

                div.appendChild(input);
                div.appendChild(label);
                checkboxContainer.appendChild(div);
            }});

            // 2. 搜索功能
            function performSearch() {{
                var keyword = document.getElementById('searchInput').value.trim().toLowerCase();
                var statusDiv = document.getElementById('search-status');
                
                if (!keyword) {{
                    // 如果搜索框为空，清空高亮
                    myChart.dispatchAction({{ type: 'downplay', seriesIndex: 0 }});
                    statusDiv.innerHTML = "";
                    return;
                }}

                var matchedNodeIndices = [];
                
                // 遍历所有节点
                graphNodes.forEach(function(node, index) {{
                    // 获取该节点的类别名称
                    var catName = graphCategories[node.category].name;
                    
                    // 只有当该类别处于“显示”状态时，才进行搜索匹配
                    if (selectedCategories[catName]) {{
                        // 匹配节点名称
                        if (node.name.toLowerCase().includes(keyword)) {{
                            matchedNodeIndices.push(index);
                        }}
                    }}
                }});

                // 遍历所有连线 (支持搜索关系名)
                graphLinks.forEach(function(link) {{
                    if (link.value && link.value.toLowerCase().includes(keyword)) {{
                        // 反查 source 和 target 的索引
                        var sIdx = graphNodes.findIndex(n => n.name === link.source);
                        var tIdx = graphNodes.findIndex(n => n.name === link.target);
                        
                        // 确保 source 和 target 都是可见的
                        if (sIdx !== -1 && tIdx !== -1) {{
                            var sCat = graphCategories[graphNodes[sIdx].category].name;
                            var tCat = graphCategories[graphNodes[tIdx].category].name;
                            
                            if (selectedCategories[sCat] && selectedCategories[tCat]) {{
                                if (!matchedNodeIndices.includes(sIdx)) matchedNodeIndices.push(sIdx);
                                if (!matchedNodeIndices.includes(tIdx)) matchedNodeIndices.push(tIdx);
                            }}
                        }}
                    }}
                }});

                if (matchedNodeIndices.length === 0) {{
                    statusDiv.innerHTML = "❌ 无可见匹配项";
                    myChart.dispatchAction({{ type: 'downplay', seriesIndex: 0 }});
                    return;
                }}

                statusDiv.innerHTML = "✅ 高亮 " + matchedNodeIndices.length + " 个节点";

                // 先取消之前的高亮
                myChart.dispatchAction({{ type: 'downplay', seriesIndex: 0 }});
                
                // 触发高亮 (Emphasis)
                myChart.dispatchAction({{
                    type: 'highlight',
                    seriesIndex: 0,
                    dataIndex: matchedNodeIndices
                }});
            }}

            // 3. 重置视图
            function resetView() {{
                // 清空搜索框
                document.getElementById('searchInput').value = "";
                document.getElementById('search-status').innerHTML = "";

                // 恢复所有复选框为勾选
                var checkboxes = checkboxContainer.querySelectorAll('input[type="checkbox"]');
                checkboxes.forEach(function(cb) {{
                    if (!cb.checked) {{
                        cb.checked = true;
                        // 触发事件让图表恢复显示
                        myChart.dispatchAction({{
                            type: 'legendSelect',
                            name: cb.value
                        }});
                        selectedCategories[cb.value] = true;
                    }}
                }});

                // 取消所有高亮
                myChart.dispatchAction({{ type: 'downplay', seriesIndex: 0 }});
                
                // 恢复缩放和平移 (可选)
                myChart.dispatchAction({{
                    type: 'restore'
                }});
            }}
        </script>
    </body>
    </html>
    """

    out_path = output_file or OUTPUT_FILE
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    abs_path = os.path.abspath(out_path)
    print(f"✅ 最终版可视化生成成功！请在浏览器中打开: {abs_path}")
    return abs_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="根据知识图谱 JSON 生成 ECharts 力导向图 HTML (含显隐控制与搜索)")
    parser.add_argument("json_file", nargs="?", default=INPUT_FILE, help=f"输入的 JSON 文件 (默认: {INPUT_FILE})")
    parser.add_argument("-o", "--output", default=OUTPUT_FILE, help=f"输出的 HTML 文件 (默认: {OUTPUT_FILE})")
    args = parser.parse_args()
    generate_html(args.json_file, args.output)