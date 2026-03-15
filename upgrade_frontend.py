import os
from pathlib import Path

def patch_app_frontend():
    fpath = Path("app.py")
    content = fpath.read_text(encoding="utf-8")

    # 匹配旧的渲染逻辑
    old_block = """    with tab_product:
        df_prod = pd.DataFrame([e for e in entities if e['type'] == 'product'])
        if not df_prod.empty:
            st.dataframe(df_prod[['name', 'description', 'created_at']], use_container_width=True, hide_index=True)"""

    # 全新的渲染逻辑：解析 attributes_json 并配置精美表头
    new_block = """    with tab_product:
        prod_list = [e.copy() for e in entities if e['type'] == 'product']
        if prod_list:
            import json
            for p in prod_list:
                attr_str = p.get('attributes_json')
                if attr_str:
                    try:
                        attrs = json.loads(attr_str)
                        for k, v in attrs.items():
                            # 将列表转换为逗号分隔的字符串，否则表格无法完美渲染
                            p[k] = ", ".join(v) if isinstance(v, list) else str(v)
                    except:
                        pass

            df_prod = pd.DataFrame(prod_list)

            # 定义期望展示的列和专业的列名映射
            col_mapping = {
                "name": "🚀 产品名称",
                "parameters_size": "🧮 参数量级",
                "context_window": "📚 上下文",
                "is_open_source": "🔓 开源",
                "architecture": "🏗️ 架构",
                "modalities": "👁️ 支持模态",
                "base_model": "🧬 底座模型",
                "pricing_model": "💰 定价模式",
                "description": "📝 简介"
            }

            # 只提取数据中真实存在的列，防止报错
            existing_cols = [c for c in col_mapping.keys() if c in df_prod.columns]

            st.dataframe(
                df_prod[existing_cols],
                use_container_width=True,
                hide_index=True,
                column_config=col_mapping
            )
        else:
            st.info("暂无产品数据。")"""

    if "st.dataframe(df_prod[['name', 'description', 'created_at']]" in content:
        content = content.replace(old_block, new_block)
        fpath.write_text(content, encoding="utf-8")
        print("✅ app.py 前端产品库表格升级完成！")
    else:
        print("⚠️ 未找到匹配的旧代码块，请检查 app.py。")

if __name__ == '__main__':
    patch_app_frontend()
