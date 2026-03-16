<div align="center">

# ⚡️ OSINT Tracker V4.0 | AI 产业追踪雷达

**军用级开源情报（OSINT）全栈平台 · 基于多模态大模型与图谱 RAG 技术**

[![React](https://img.shields.io/badge/Frontend-React%2018-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://reactjs.org/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![TailwindCSS](https://img.shields.io/badge/UI-Tailwind%20v4-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)
[![SQLite](https://img.shields.io/badge/Database-SQLite%20WAL-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://sqlite.org/)

> *"In the age of AI, information is not power. Structured intelligence is."*<br>
> 在 AI 爆发的时代，信息不再是力量，**结构化的情报才是。**

</div>

---

## 📖 平台概览 (Overview)

![指挥中心演示](./assets/ops_center.png)

![战术图谱演示](./assets/tactical_graph.png)

**OSINT Tracker v4.0** 是一个专为 AI 行业研究员、投资人及战略决策者打造的**自动化情报追踪与推演系统**。
它摒弃了传统爬虫“只管抓不管看”的痛点，采用 **V8 高并发解析底座** 配合 **L2/L3 双轨大模型引擎**，实现从“全网非结构化信息”到“高维可视化战术图谱”的毫秒级升维。

### 核心设计哲学
- **自动化剥离噪音**：通过 LLM 从万字研报中精准提炼公司、产品、技术实体及深层交互关系。
- **暗黑极客美学**：全沉浸式玻璃拟态 UI，专为长时间高强度情报研判设计。
- **绝对的数据主权**：基于 SQLite WAL 构建的本地高性能知识库，所有商业机密与战略推演绝不外流。

---

## 🚀 核心战术模块 (Core Capabilities)

### 🎛️ 1. 指挥中心 (Ops Center)
- **多模态接收舱**：支持网页 URL 直连抓取，以及 PDF、Word 等深度研报的拖拽解析（由 `MarkItDown` 驱动）。
- **高并发任务引擎**：内置后台异步 Worker 列车，实时监控 Pending / Processing 队列吞吐状态。

### 📚 2. 情报大盘 (Intelligence DB)
- **L2 级风险预警引擎**：自动对产业事件打上「高危」、「利好」、「中风险」红绿灯标签，产业动向一目了然。
- **全息资产矩阵**：动态解析并结构化 AI 产品的硬核参数（如：参数量级、上下文窗口、开源协议、支持模态）。

### 🕸️ 3. 战术图谱 (Tactical Graph)
- **引力物理引擎**：基于 `react-force-graph` 构建的动态 2D 关系网。
- **全景溯源**：万级节点流畅拖拽，实时呈现公司收购、产品发布、高管变动等复杂关系涟漪。

### 💬 4. 参谋部 (Strategic Copilot)
- **L3 级深度推演**：搭载基于图谱 RAG 检索的智能参谋大模型。
- **沙盘问答**：支持对本地情报库进行“链式追问”、“风险预判”与“战略对比”，并以 Markdown 格式优雅输出。

---

## 🛠️ 技术栈基石 (Tech Stack)

| 领域 | 核心技术 | 描述 |
| :--- | :--- | :--- |
| **Frontend** | React + TypeScript + Vite | 极致响应速度，严格类型约束 |
| **UI / Styling**| Tailwind CSS v4 + Lucide | 现代玻璃拟态组件与高品质图标库 |
| **Backend** | FastAPI (Python 3.10+) | 高并发异步 API，承载前后端融合分发 |
| **Database** | SQLite3 (WAL Mode) | 防锁死并发写入，零配置的极致性能 |
| **AI / NLP** | OpenAI API / LangChain | 实体抽取 (Extractor) 与 推演 (RAG) |
| **Parsing** | Microsoft MarkItDown | 暴力破解全格式文档 (PDF/PPT/DOCX) |
| **Graph** | react-force-graph-2d | 基于 Canvas 的大规模节点引力渲染引擎 |

---

## ⚙️ 极速部署 (Quick Start)

系统已实现**前后端全栈融合**，仅需启动单一 Python 进程即可接管全域防务。

### 1. 克隆阵地
```bash
git clone https://github.com/kcdyx1/ai_tracker_system.git
cd ai-tracker-system
```
### 2. 配置环境密钥
在根目录创建 .env 文件并注入你的大模型 API 密钥：

```
OPENAI_API_KEY=sk-your-api-key-here
BASE_URL=[https://api.openai.com/v1](https://api.openai.com/v1)  # 可选：修改为你的代理端点
```

### 3. 安装弹药库 (后端依赖)
```Bash
# 推荐使用虚拟环境
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install "markitdown[all]"  # 装载多模态解析穿甲弹
```

### 4. 点火升空！
```Bash
# 启动 FastAPI 后台及 React 前端融合服务
python server.py
```

🌐 启动成功后，在浏览器访问: http://localhost:8000 即可进入指挥中心。

(注：开发环境下如需修改前端代码，请进入 frontend 目录执行 npm run dev；修改完成后执行 npm run build 将最新产物交由后端接管。)

---

📂 系统架构目录 (Architecture)
```Plaintext
ai_tracker_system/
├── server.py             # 🧠 后端主基地 & API 路由网关
├── database.py           # 🗄️ SQLite WAL 高并发存储层
├── ontology.py           # 🧬 Pydantic 数据本体 (含 L2 红绿灯字段)
├── extractor.py          # 🔪 拆解车间 (LLM 实体关系抽取)
├── rag.py                # 💬 L3 参谋部战略推演引擎
├── data/                 # 💾 本地加密数据库与文档沙盒
└── frontend/             # 🎨 现代 React 前端基地
    ├── dist/             # 📦 编译后的静态交付物 (由 server.py 分发)
    └── src/
        ├── App.tsx       # 🖥️ 核心战术组件面板
        └── index.css     # 极客暗黑主题引擎
```

🛡️ License
本项目采用 MIT License 授权。
欢迎任何形式的 Pull Request 来扩充这台雷达的侦测边界！