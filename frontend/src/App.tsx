import { useState, useEffect, useRef, useCallback } from 'react'
import { Activity, Database, Network, MessageSquare, Layers, Calendar, Building2, Package, UserIcon, ExternalLink, AlertTriangle, TrendingUp, Maximize2, Send, Bot, UploadCloud, Link, FileText, CheckCircle2, XCircle, Clock, Loader2 } from 'lucide-react'
import axios from 'axios'
import ForceGraph2D from 'react-force-graph-2d'
import ReactMarkdown from 'react-markdown'

// ============================================================================
// 数据类型接口
// ============================================================================
interface Stats { entity_count: number; event_count: number; relationship_count: number; company_count: number; product_count: number; }
interface Task { id: number; url: string; status: string; error_message: string; created_at: string; }
interface EventItem { id: string; title: string; date: string; summary: string; risk_level: string | null; sentiment: string | null; source_url: string | null; }
interface EntityItem { id: string; type: string; name: string; description: string; attributes_json: string; created_at: string; }
interface GraphData { nodes: any[]; links: any[] }
interface ChatMessage { role: 'user' | 'assistant'; content: string; }

// ============================================================================
// 组件 1: 🎛️ 指挥中心 (Ops Center) - 带多模态情报接收舱版
// ============================================================================
const OpsCenter = () => {
  const [stats, setStats] = useState<Stats | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [taskStats, setTaskStats] = useState({ pending: 0, processing: 0, completed: 0, failed: 0 })
  const [loading, setLoading] = useState(true)

  // 接收舱相关状态
  const [activeIngestTab, setActiveIngestTab] = useState<'url' | 'file'>('url')
  const [urlInput, setUrlInput] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [ingestStatus, setIngestStatus] = useState<{ type: 'success' | 'error', msg: string } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const fetchData = async () => {
    try {
      const [statsRes, tasksRes, taskStatsRes] = await Promise.all([
        axios.get('/api/stats'),
        axios.get('/api/tasks'),
        axios.get('/api/task_stats') // 💡 新增的状态拉取
      ])
      setStats(statsRes.data); setTasks(tasksRes.data); setTaskStats(taskStatsRes.data)
    } catch (error) { console.error(error) } finally { setLoading(false) }
  }

  useEffect(() => { fetchData(); const interval = setInterval(fetchData, 5000); return () => clearInterval(interval) }, [])

  // 提交 URL
  const handleUrlSubmit = async () => {
    if (!urlInput.trim()) return
    setIsSubmitting(true); setIngestStatus(null)
    try {
      await axios.post('/api/ingest', { url: urlInput })
      setIngestStatus({ type: 'success', msg: `🎯 链接已成功送入情报雷达阵列！` })
      setUrlInput(''); fetchData()
    } catch (error) {
      setIngestStatus({ type: 'error', msg: `❌ 链接解析失败，请检查格式。` })
    } finally { setIsSubmitting(false) }
  }

  // 上传文件
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setIsSubmitting(true); setIngestStatus(null)
    const formData = new FormData()
    formData.append('file', file)
    try {
      await axios.post('/api/upload', formData)
      setIngestStatus({ type: 'success', msg: `📄 文档 '${file.name}' 已送入装填弹仓！` })
      fetchData()
    } catch (error) {
      setIngestStatus({ type: 'error', msg: `❌ 文档上传失败。` })
    } finally {
      setIsSubmitting(false); if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const StatusBadge = ({ status }: { status: string }) => {
    const styles: Record<string, string> = { completed: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20", processing: "bg-amber-500/10 text-amber-400 border-amber-500/20 animate-pulse", pending: "bg-slate-500/10 text-slate-400 border-slate-500/20", failed: "bg-rose-500/10 text-rose-400 border-rose-500/20" }; return <span className={`px-2.5 py-1 rounded-md text-xs font-medium border ${styles[status] || styles.pending}`}>{status.toUpperCase()}</span>
  }

  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-700 space-y-8">
      <div><h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-teal-400 to-emerald-300">🎛️ 指挥中心 (Ops Center)</h1><p className="text-slate-400 mt-2">全局数据概览与高并发引擎状态监控</p></div>
      
      {/* 核心大盘数字 */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {[ { label: "总实体数", value: stats?.entity_count, icon: <Database className="w-5 h-5 text-teal-400" /> }, { label: "总事件数", value: stats?.event_count, icon: <Activity className="w-5 h-5 text-emerald-400" /> }, { label: "总关系数", value: stats?.relationship_count, icon: <Network className="w-5 h-5 text-indigo-400" /> }, { label: "收录公司", value: stats?.company_count, icon: <Building2 className="w-5 h-5 text-amber-400" /> }, { label: "收录产品", value: stats?.product_count, icon: <Package className="w-5 h-5 text-rose-400" /> } ].map((item, idx) => (
          <div key={idx} className="relative group overflow-hidden backdrop-blur-md bg-slate-900/40 border border-slate-700/50 rounded-2xl p-6 transition-all hover:-translate-y-1 hover:border-teal-500/30 hover:shadow-[0_8px_30px_rgb(20,184,166,0.12)]">
            <div className="flex justify-between items-start mb-4"><p className="text-sm font-medium text-slate-400">{item.label}</p>{item.icon}</div>
            <p className="text-3xl font-bold text-slate-100 font-mono">{loading ? "..." : (item.value || 0).toLocaleString()}</p>
          </div>
        ))}
      </div>

      {/* 🚀 新增：多模态情报接收舱 */}
      <div className="backdrop-blur-md bg-slate-900/40 border border-slate-700/50 rounded-2xl p-6 relative overflow-hidden">
        <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-teal-500 to-emerald-400 opacity-50"></div>
        <h3 className="text-lg font-semibold flex items-center text-slate-200 mb-5">
          <UploadCloud className="w-5 h-5 mr-2 text-teal-400" /> 多模态情报接收舱
        </h3>
        
        {/* Tab 切换 */}
        <div className="flex space-x-4 border-b border-slate-800 mb-5">
          <button onClick={() => setActiveIngestTab('url')} className={`pb-3 text-sm font-medium border-b-2 transition-colors ${activeIngestTab === 'url' ? 'border-teal-400 text-teal-400' : 'border-transparent text-slate-400 hover:text-slate-300'}`}>🔗 网页直连 (Web Ingest)</button>
          <button onClick={() => setActiveIngestTab('file')} className={`pb-3 text-sm font-medium border-b-2 transition-colors ${activeIngestTab === 'file' ? 'border-teal-400 text-teal-400' : 'border-transparent text-slate-400 hover:text-slate-300'}`}>📄 深度文档解析 (File Upload)</button>
        </div>

        {/* URL 输入框 */}
        {activeIngestTab === 'url' && (
          <div className="flex gap-3">
            <input type="text" value={urlInput} onChange={e => setUrlInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && handleUrlSubmit()} placeholder="在此粘贴行业新闻、博客或研报的 URL 链接 (https://...)" disabled={isSubmitting} className="flex-1 bg-slate-950 border border-slate-700 rounded-xl px-4 py-3 text-sm text-slate-200 focus:outline-none focus:border-teal-500/50 focus:ring-1 focus:ring-teal-500/50 transition-all placeholder:text-slate-600" />
            <button onClick={handleUrlSubmit} disabled={isSubmitting || !urlInput.trim()} className="bg-teal-600 hover:bg-teal-500 disabled:opacity-50 text-white px-6 py-3 rounded-xl text-sm font-medium transition-colors flex items-center shadow-lg shadow-teal-900/20">
              {isSubmitting ? <Loader2 className="w-4 h-4 mr-2 animate-spin"/> : <Link className="w-4 h-4 mr-2"/>} {isSubmitting ? '传输中...' : '提交目标'}
            </button>
          </div>
        )}

        {/* 拖拽文件上传框 */}
        {activeIngestTab === 'file' && (
          <div className="w-full">
            <input type="file" ref={fileInputRef} onChange={handleFileUpload} accept=".pdf,.docx,.txt,.md" className="hidden" id="file-upload" />
            <label htmlFor="file-upload" className={`border-2 border-dashed ${isSubmitting ? 'border-teal-500/50 bg-teal-900/10' : 'border-slate-700 hover:border-teal-500/50 bg-slate-950/50'} rounded-xl px-4 py-8 flex flex-col items-center justify-center cursor-pointer transition-colors text-slate-400 hover:text-teal-400`}>
                {isSubmitting ? <Loader2 className="w-10 h-10 animate-spin mb-3 text-teal-400"/> : <FileText className="w-10 h-10 mb-3"/>}
                <span className="text-sm font-medium">{isSubmitting ? '正在将文档传输至解析中枢...' : '点击或拖拽上传行业研报、财报、白皮书'}</span>
                <span className="text-xs text-slate-500 mt-2">支持格式: PDF, Word, Markdown (单文件推荐小于 50 MB)</span>
            </label>
          </div>
        )}

        {/* 状态反馈条 */}
        {ingestStatus && (
          <div className={`mt-4 p-3 rounded-lg text-sm flex items-center animate-in fade-in ${ingestStatus.type === 'success' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'}`}>
            {ingestStatus.type === 'success' ? <CheckCircle2 className="w-4 h-4 mr-2"/> : <XCircle className="w-4 h-4 mr-2"/>} {ingestStatus.msg}
          </div>
        )}
      </div>

      {/* 🚀 新增：引擎队列统计卡片 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-slate-900/40 border border-slate-700/50 rounded-xl p-4 flex items-center justify-between"><div><p className="text-xs text-slate-400 mb-1">⏳ 缓冲队列 (Pending)</p><p className="text-xl font-bold text-slate-200 font-mono">{taskStats.pending}</p></div><Clock className="w-8 h-8 text-slate-500 opacity-30"/></div>
        <div className="bg-amber-900/10 border border-amber-700/30 rounded-xl p-4 flex items-center justify-between"><div><p className="text-xs text-amber-500/70 mb-1">🔄 引擎吞吐 (Processing)</p><p className="text-xl font-bold text-amber-400 font-mono">{taskStats.processing}</p></div><Activity className="w-8 h-8 text-amber-500 opacity-30 animate-pulse"/></div>
        <div className="bg-emerald-900/10 border border-emerald-700/30 rounded-xl p-4 flex items-center justify-between"><div><p className="text-xs text-emerald-500/70 mb-1">✅ 完美解析 (Completed)</p><p className="text-xl font-bold text-emerald-400 font-mono">{taskStats.completed}</p></div><CheckCircle2 className="w-8 h-8 text-emerald-500 opacity-30"/></div>
        <div className="bg-rose-900/10 border border-rose-700/30 rounded-xl p-4 flex items-center justify-between"><div><p className="text-xs text-rose-500/70 mb-1">❌ 异常脱落 (Failed)</p><p className="text-xl font-bold text-rose-400 font-mono">{taskStats.failed}</p></div><XCircle className="w-8 h-8 text-rose-500 opacity-30"/></div>
      </div>

      <div className="backdrop-blur-md bg-slate-900/40 border border-slate-700/50 rounded-2xl overflow-hidden">
        <div className="px-6 py-5 border-b border-slate-700/50 flex justify-between items-center bg-slate-800/20"><h3 className="text-lg font-semibold flex items-center text-slate-200"><Layers className="w-5 h-5 mr-2 text-teal-400" /> V8 并发解析引擎列车</h3><span className="flex items-center text-xs text-slate-400 bg-slate-950/50 px-3 py-1 rounded-full border border-slate-700"><span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping mr-2"></span>实时同步中</span></div>
        <div className="overflow-x-auto"><table className="w-full text-sm text-left"><thead className="text-xs text-slate-400 uppercase bg-slate-900/50 border-b border-slate-800"><tr><th className="px-6 py-4">任务ID</th><th className="px-6 py-4">目标 URL / 文档</th><th className="px-6 py-4">状态</th><th className="px-6 py-4">异常信息</th><th className="px-6 py-4">入列时间</th></tr></thead><tbody className="divide-y divide-slate-800/50">
          {tasks.map((task) => (<tr key={task.id} className="hover:bg-slate-800/30 transition-colors"><td className="px-6 py-4 font-mono text-slate-500">#{task.id}</td><td className="px-6 py-4 text-slate-300 truncate max-w-[200px] xl:max-w-xs">{task.url.replace('file://', '📄 ').replace('https://', '🔗 ')}</td><td className="px-6 py-4"><StatusBadge status={task.status} /></td><td className="px-6 py-4 text-rose-400/80 truncate max-w-xs" title={task.error_message || ''}>{task.error_message || '-'}</td><td className="px-6 py-4 text-slate-500 font-mono">{new Date(task.created_at).toLocaleString()}</td></tr>))}
          {tasks.length === 0 && !loading && <tr><td colSpan={5} className="px-6 py-8 text-center text-slate-500">队列空闲中，请在上方输入链接或拖拽文档投喂情报...</td></tr>}
        </tbody></table></div>
      </div>
    </div>
  )
}

// ============================================================================
// 下面组件 2、3、4 完全保持不变 (直接接上)
// ============================================================================
// ============================================================================
// 组件 2: 📚 情报大盘 (Intelligence Dashboard) - 满血修复版
// ============================================================================
// ============================================================================
// 组件 2: 📚 情报大盘 (Intelligence Dashboard) - 火力全开满血版
// ============================================================================
const IntelligenceDashboard = () => {
  const [events, setEvents] = useState<EventItem[]>([])
  const [entities, setEntities] = useState<EntityItem[]>([])
  const [subTab, setSubTab] = useState<'timeline'|'company'|'product'|'person'|'tech_concept'>('timeline')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const loadData = async () => {
      try {
        const [evRes, entRes] = await Promise.all([axios.get('/api/events'), axios.get('/api/entities')])
        setEvents(evRes.data)
        setEntities(entRes.data)
      } catch (error) { console.error(error) } finally { setLoading(false) }
    }
    loadData()
  }, [])

  const parseJson = (str: string) => { 
    if (!str) return {};
    try { const parsed = JSON.parse(str); return (parsed && typeof parsed === 'object') ? parsed : {}; } 
    catch { return {}; } 
  }

  const subTabs = [
    { id: 'timeline', label: '产业时间线', icon: <Calendar className="w-4 h-4 mr-2" /> },
    { id: 'company', label: '公司库', icon: <Building2 className="w-4 h-4 mr-2" /> },
    { id: 'product', label: 'AI 产品库', icon: <Package className="w-4 h-4 mr-2" /> },
    { id: 'person', label: '人物库', icon: <UserIcon className="w-4 h-4 mr-2" /> },
    { id: 'tech_concept', label: '技术概念', icon: <Layers className="w-4 h-4 mr-2" /> },
  ]

  const renderL2Tags = (risk: string | null, sentiment: string | null) => {
    if (!risk && !sentiment) return null;
    return (
      <div className="flex gap-2 mt-2">
        {risk === '高危' && <span className="flex items-center px-2 py-0.5 rounded text-xs font-medium bg-rose-500/20 text-rose-400 border border-rose-500/30"><AlertTriangle className="w-3 h-3 mr-1"/>高危预警</span>}
        {risk === '中风险' && <span className="flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-500/20 text-amber-400 border border-amber-500/30">中度风险</span>}
        {sentiment === '利好' && <span className="flex items-center px-2 py-0.5 rounded text-xs font-medium bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"><TrendingUp className="w-3 h-3 mr-1"/>商业利好</span>}
        {sentiment === '利空' && <span className="flex items-center px-2 py-0.5 rounded text-xs font-medium bg-rose-500/20 text-rose-400 border border-rose-500/30">商业利空</span>}
      </div>
    )
  }

  // 辅助函数：安全渲染数组或字符串
  const renderAttr = (val: any) => Array.isArray(val) ? val.join(', ') : String(val);

  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-700 space-y-6">
      <div>
        <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-cyan-400">📚 情报大盘 (Intelligence DB)</h1>
        <p className="text-slate-400 mt-2">结构化情报流与全景资产库</p>
      </div>

      <div className="flex space-x-2 border-b border-slate-800 pb-px overflow-x-auto">
        {subTabs.map(tab => (
          <button key={tab.id} onClick={() => setSubTab(tab.id as any)}
            className={`flex items-center px-4 py-2 text-sm font-medium rounded-t-lg transition-colors border-b-2 whitespace-nowrap ${
              subTab === tab.id ? 'border-cyan-400 text-cyan-400 bg-cyan-400/10' : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}>
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      <div className="min-h-[500px]">
        {loading ? (
          <div className="flex h-64 items-center justify-center text-slate-500 animate-pulse">正在从数据库提取加密情报...</div>
        ) : (
          <>
            {/* 1. 时间线 */}
            {subTab === 'timeline' && (
              <div className="space-y-4">
                {events.map(ev => (
                  <div key={ev.id} className={`p-5 rounded-xl border backdrop-blur-sm transition-all hover:bg-slate-800/40 ${ev.risk_level === '高危' ? 'border-rose-500/30 bg-rose-950/10' : 'border-slate-800 bg-slate-900/30'}`}>
                    <div className="flex justify-between items-start">
                      <h3 className="text-lg font-semibold text-slate-200">{ev.title}</h3>
                      <span className="text-xs font-mono text-slate-500">{ev.date.substring(0, 10)}</span>
                    </div>
                    {renderL2Tags(ev.risk_level, ev.sentiment)}
                    <p className="mt-3 text-sm text-slate-400 leading-relaxed">{ev.summary}</p>
                    {ev.source_url && <a href={ev.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center mt-3 text-xs text-cyan-400 hover:text-cyan-300"><ExternalLink className="w-3 h-3 mr-1" /> 溯源验证</a>}
                  </div>
                ))}
              </div>
            )}

            {/* 2. 产品库 (满血版：所有参数全景展示) */}
            {subTab === 'product' && (
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                {entities.filter(e => e.type === 'product').map(prod => {
                  const attrs = parseJson(prod.attributes_json)
                  return (
                    <div key={prod.id} className="p-5 rounded-xl border border-slate-800 bg-slate-900/30 hover:border-cyan-500/30 transition-colors flex flex-col">
                      <div className="flex justify-between items-start mb-3">
                        <h3 className="text-lg font-bold text-cyan-300 flex items-center"><Package className="w-5 h-5 mr-2"/> {prod.name}</h3>
                        <div className="flex gap-2">
                          {attrs.is_open_source === true && <span className="px-2 py-0.5 rounded text-xs bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">开源</span>}
                          {attrs.is_open_source === false && <span className="px-2 py-0.5 rounded text-xs bg-slate-700/50 text-slate-400 border border-slate-600">闭源</span>}
                        </div>
                      </div>
                      
                      <p className="text-sm text-slate-400 mb-5 line-clamp-2 leading-relaxed">{prod.description}</p>
                      
                      {/* ⚡️ 硬核参数网格 (动态拉取所有被隐藏的数据) */}
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs mb-4 flex-1">
                        {attrs.parameters_size && <div className="p-2 rounded bg-slate-950/50 border border-slate-800"><span className="text-slate-500 block mb-1">参数量级</span><span className="font-mono text-slate-200">{attrs.parameters_size}</span></div>}
                        {attrs.context_window && <div className="p-2 rounded bg-slate-950/50 border border-slate-800"><span className="text-slate-500 block mb-1">上下文窗口</span><span className="font-mono text-slate-200">{attrs.context_window}</span></div>}
                        {attrs.architecture && <div className="p-2 rounded bg-slate-950/50 border border-slate-800"><span className="text-slate-500 block mb-1">模型架构</span><span className="font-mono text-slate-200">{attrs.architecture}</span></div>}
                        {attrs.modalities && attrs.modalities.length > 0 && <div className="p-2 rounded bg-slate-950/50 border border-slate-800"><span className="text-slate-500 block mb-1">支持模态</span><span className="font-mono text-slate-200 truncate block" title={renderAttr(attrs.modalities)}>{renderAttr(attrs.modalities)}</span></div>}
                        {attrs.base_model && <div className="p-2 rounded bg-slate-950/50 border border-slate-800"><span className="text-slate-500 block mb-1">底层依赖</span><span className="font-mono text-slate-200 truncate block" title={attrs.base_model}>{attrs.base_model}</span></div>}
                        {attrs.pricing_model && <div className="p-2 rounded bg-slate-950/50 border border-slate-800"><span className="text-slate-500 block mb-1">商业模式</span><span className="font-mono text-slate-200 truncate block" title={attrs.pricing_model}>{attrs.pricing_model}</span></div>}
                      </div>

                      {/* 底部代码与协议链接 */}
                      <div className="flex flex-wrap gap-4 mt-auto pt-3 border-t border-slate-800/50 text-xs">
                        {attrs.github_url && <a href={attrs.github_url} target="_blank" rel="noreferrer" className="flex items-center text-slate-400 hover:text-cyan-400 transition-colors"><ExternalLink className="w-3 h-3 mr-1"/> GitHub</a>}
                        {attrs.paper_url && <a href={attrs.paper_url} target="_blank" rel="noreferrer" className="flex items-center text-slate-400 hover:text-cyan-400 transition-colors"><ExternalLink className="w-3 h-3 mr-1"/> 论文文献</a>}
                        {attrs.license_type && <span className="flex items-center text-slate-500"><AlertTriangle className="w-3 h-3 mr-1"/>协议: {attrs.license_type}</span>}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}

            {/* 3. 公司、人物、技术库通用列表 (带扩展参数 Badge 标签) */}
            {['company', 'person', 'tech_concept'].includes(subTab) && (
              <div className="rounded-xl border border-slate-800 overflow-hidden">
                <table className="w-full text-sm text-left">
                  <thead className="bg-slate-900/80 border-b border-slate-800 text-slate-400">
                    <tr><th className="px-6 py-3 w-1/4">名称</th><th className="px-6 py-3 w-1/2">简介与扩展参数</th><th className="px-6 py-3 w-1/4">收录时间</th></tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/50 bg-slate-900/30">
                    {entities.filter(e => e.type === subTab).map(ent => {
                      const attrs = parseJson(ent.attributes_json)
                      // 翻译常用的扩展字段键名
                      const keyMap: Record<string, string> = { founded_year: "成立", website: "官网", status: "状态", current_title: "现任职务", category: "技术分类" }
                      
                      return (
                        <tr key={ent.id} className="hover:bg-slate-800/50 transition-colors">
                          <td className="px-6 py-4 font-medium text-slate-200 align-top">{ent.name}</td>
                          <td className="px-6 py-4 align-top">
                            <div className="text-slate-400 leading-relaxed">{ent.description || '-'}</div>
                            {/* ⚡️ 渲染所有扩展属性标签 */}
                            <div className="flex flex-wrap gap-2 mt-3">
                              {Object.entries(attrs).map(([k, v]) => {
                                if (!v || v === 'null' || (Array.isArray(v) && v.length === 0)) return null;
                                return (
                                  <span key={k} className="inline-flex items-center px-2 py-1 rounded bg-slate-950 border border-slate-800 text-[11px] text-slate-300">
                                    <span className="text-slate-500 mr-1">{keyMap[k] || k}:</span>
                                    {k === 'website' ? <a href={String(v)} target="_blank" rel="noreferrer" className="text-cyan-400 hover:underline">访问</a> : <span className="font-mono">{renderAttr(v)}</span>}
                                  </span>
                                )
                              })}
                            </div>
                          </td>
                          <td className="px-6 py-4 text-slate-500 font-mono text-xs align-top">{ent.created_at.substring(0, 10)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                {entities.filter(e => e.type === subTab).length === 0 && (
                  <div className="p-8 text-center text-slate-500">此维度目前暂无相关数据入库。</div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

const TacticalGraph = () => {
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] }); const [loading, setLoading] = useState(true); const fgRef = useRef<any>(null)
  const colorMap: Record<string, string> = { company: '#3b82f6', product: '#ec4899', person: '#10b981', tech_concept: '#8b5cf6' }
  useEffect(() => { const fetchGraph = async () => { try { const res = await axios.get('/api/graph'); setGraphData(res.data) } catch (error) { console.error(error) } finally { setLoading(false) } }; fetchGraph() }, [])
  const drawNode = useCallback((node: any, ctx: CanvasRenderingContext2D, globalScale: number) => { const label = node.name; const fontSize = 12 / globalScale; const nodeColor = colorMap[node.type] || '#ffffff'; ctx.beginPath(); ctx.arc(node.x, node.y, 6, 0, 2 * Math.PI, false); ctx.fillStyle = nodeColor; ctx.shadowColor = nodeColor; ctx.shadowBlur = 10; ctx.fill(); ctx.shadowBlur = 0; ctx.font = `${fontSize}px Sans-Serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = '#e2e8f0'; ctx.fillText(label, node.x, node.y + 12); }, []);
  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-700 h-[calc(100vh-80px)] flex flex-col">
      <div className="mb-4 flex justify-between items-end">
        <div><h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-indigo-400 flex items-center"><Network className="w-8 h-8 mr-3 text-blue-400" />战术图谱 (Tactical Graph)</h1><p className="text-slate-400 mt-2">基于物理引力引擎的动态实体关系网</p></div>
        <div className="flex gap-3 text-xs">{Object.entries(colorMap).map(([type, color]) => (<span key={type} className="flex items-center px-2 py-1 rounded-md bg-slate-900 border border-slate-800"><span className="w-3 h-3 rounded-full mr-2" style={{ backgroundColor: color }}></span>{type.toUpperCase()}</span>))}</div>
      </div>
      <div className="flex-1 relative rounded-2xl overflow-hidden border border-slate-700/50 bg-[#020617] shadow-2xl">
        {loading ? <div className="absolute inset-0 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm z-10"><div className="flex flex-col items-center"><Network className="w-12 h-12 text-blue-500 animate-spin mb-4" /><p className="text-slate-400">正在构建引力场与节点连接...</p></div></div> : graphData.nodes.length === 0 ? <div className="absolute inset-0 flex items-center justify-center text-slate-500">暂无图谱数据，请先前往指挥中心摄入情报</div> : (
          <><ForceGraph2D ref={fgRef} graphData={graphData} nodeCanvasObject={drawNode} nodePointerAreaPaint={(node, color, ctx) => { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(node.x, node.y, 8, 0, 2 * Math.PI, false); ctx.fill(); }} linkColor={() => 'rgba(148, 163, 184, 0.3)'} linkDirectionalArrowLength={3.5} linkDirectionalArrowRelPos={1} linkLabel="label" onEngineStop={() => fgRef.current?.zoomToFit(400, 50)} d3VelocityDecay={0.1} cooldownTicks={100} />
            <div className="absolute bottom-4 right-4 bg-slate-900/80 backdrop-blur-md p-2 rounded-lg border border-slate-700 flex gap-2"><button onClick={() => fgRef.current?.zoomToFit(400, 50)} className="p-2 hover:bg-slate-800 rounded text-slate-400 hover:text-white transition-colors" title="重置视角"><Maximize2 className="w-5 h-5" /></button></div></>
        )}
      </div>
    </div>
  )
}

const CopilotChat = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([{ role: 'assistant', content: '指挥官您好，我是本系统的首席战略官。情报雷达已待命，请下达分析指令。' }])
  const [input, setInput] = useState(''); const [isLoading, setIsLoading] = useState(false); const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollToBottom = () => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }) }
  useEffect(() => { scrollToBottom() }, [messages])
  const handleSend = async () => {
    if (!input.trim() || isLoading) return
    const userMsg = input.trim(); setInput(''); setMessages(prev => [...prev, { role: 'user', content: userMsg }]); setIsLoading(true)
    try {
      const res = await axios.post('/api/chat', { query: userMsg, history: messages.slice(1) })
      setMessages(prev => [...prev, { role: 'assistant', content: res.data.response }])
    } catch (error: any) { setMessages(prev => [...prev, { role: 'assistant', content: `❌ 通讯失败: ${error.message || '网络错误'}` }]) } finally { setIsLoading(false) }
  }
  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-700 h-[calc(100vh-80px)] flex flex-col">
      <div className="mb-4"><h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-purple-400 to-pink-400 flex items-center"><MessageSquare className="w-8 h-8 mr-3 text-purple-400" />参谋部 (Strategic Copilot)</h1><p className="text-slate-400 mt-2">基于图谱 RAG 检索的 L3 级深度推演大模型</p></div>
      <div className="flex-1 bg-slate-900/50 border border-slate-700/50 rounded-t-2xl p-6 overflow-y-auto space-y-6 scroll-smooth">
        {messages.map((msg, idx) => (<div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}><div className={`flex max-w-[85%] ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}><div className={`flex-shrink-0 flex items-center justify-center w-8 h-8 rounded-full ${msg.role === 'user' ? 'bg-indigo-500/20 text-indigo-400 ml-3' : 'bg-purple-500/20 text-purple-400 mr-3'}`}>{msg.role === 'user' ? <UserIcon className="w-4 h-4" /> : <Bot className="w-4 h-4" />}</div><div className={`px-5 py-3 rounded-2xl ${msg.role === 'user' ? 'bg-indigo-600/20 text-indigo-100 border border-indigo-500/30' : 'bg-slate-800/80 text-slate-200 border border-slate-700'}`}><div className="prose prose-invert prose-p:leading-relaxed prose-pre:bg-slate-900 prose-pre:border prose-pre:border-slate-700 max-w-none text-sm">{msg.role === 'user' ? msg.content : <ReactMarkdown>{msg.content}</ReactMarkdown>}</div></div></div></div>))}
        {isLoading && (<div className="flex justify-start"><div className="flex flex-row max-w-[85%]"><div className="flex-shrink-0 flex items-center justify-center w-8 h-8 rounded-full bg-purple-500/20 text-purple-400 mr-3"><Bot className="w-4 h-4" /></div><div className="px-5 py-4 rounded-2xl bg-slate-800/80 border border-slate-700 flex items-center space-x-2"><div className="w-2 h-2 rounded-full bg-purple-400 animate-bounce" style={{ animationDelay: '0ms' }}></div><div className="w-2 h-2 rounded-full bg-purple-400 animate-bounce" style={{ animationDelay: '150ms' }}></div><div className="w-2 h-2 rounded-full bg-purple-400 animate-bounce" style={{ animationDelay: '300ms' }}></div><span className="text-xs text-slate-400 ml-2">正在雷达阵列中检索底层证据并生成研判...</span></div></div></div>)}
        <div ref={messagesEndRef} />
      </div>
      <div className="p-4 bg-slate-900/80 border border-t-0 border-slate-700/50 rounded-b-2xl flex items-center"><input type="text" value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') handleSend() }} placeholder="询问产业风险、公司战略、大模型对比分析..." className="flex-1 bg-slate-950 border border-slate-700 rounded-xl px-4 py-3 text-sm text-slate-200 focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/50 transition-all placeholder:text-slate-600" disabled={isLoading} /><button onClick={handleSend} disabled={isLoading || !input.trim()} className="ml-3 p-3 rounded-xl bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed text-white transition-colors shadow-lg shadow-purple-900/20"><Send className="w-5 h-5" /></button></div>
    </div>
  )
}

function App() {
  const [activeTab, setActiveTab] = useState('ops') // 回到指挥中心默认页

  const navItems = [
    { id: 'ops', label: '指挥中心', icon: <Activity className="w-5 h-5" /> },
    { id: 'db', label: '情报大盘', icon: <Database className="w-5 h-5" /> },
    { id: 'graph', label: '战术图谱', icon: <Network className="w-5 h-5" /> },
    { id: 'chat', label: '参谋部', icon: <MessageSquare className="w-5 h-5" /> },
  ]

  return (
    <div className="min-h-screen bg-[#080d1a] text-slate-300 flex selection:bg-cyan-500/30">
      <aside className="w-64 border-r border-slate-800 bg-slate-950/50 hidden md:flex flex-col">
        <div className="p-6 border-b border-slate-800">
          <h2 className="text-xl font-bold text-white flex items-center"><Activity className="w-6 h-6 mr-2 text-cyan-400" />产业雷达</h2>
          <p className="text-xs text-slate-500 mt-1 font-mono">OSINT Platform v4.0</p>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {navItems.map((item) => (
            <button key={item.id} onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center px-4 py-3 rounded-xl transition-all duration-200 ${
                activeTab === item.id 
                  ? 'bg-purple-500/10 text-purple-400 border border-purple-500/20 shadow-[0_0_15px_rgb(168,85,247,0.1)]' 
                  : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-200 border border-transparent'
              }`}>
              {item.icon} <span className="ml-3 font-medium">{item.label}</span>
            </button>
          ))}
        </nav>
      </aside>
      <main className="flex-1 p-6 md:p-10 overflow-y-auto">
        {activeTab === 'ops' && <OpsCenter />}
        {activeTab === 'db' && <IntelligenceDashboard />}
        {activeTab === 'graph' && <TacticalGraph />}
        {activeTab === 'chat' && <CopilotChat />}
      </main>
    </div>
  )
}

export default App