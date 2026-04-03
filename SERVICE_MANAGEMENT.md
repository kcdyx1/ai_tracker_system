# 服务管理文档

本文档介绍 AI Tracker System 的 systemd 服务管理方案。

## 概述

项目使用 systemd user services + timers 实现服务的**开机自启**、**进程守护**和**定时调度**。

## 目录结构

```
ai_tracker_system/
├── manage.sh              # 服务管理脚本（主入口）
├── services.json          # 服务配置文件（定义所有服务）
└── ~/.config/systemd/user/  # systemd 单元文件（自动生成）
```

## 服务列表

| 服务ID | 类型 | 调度 | 说明 |
|--------|------|------|------|
| `ai_tracker_server` | long_running | - | FastAPI API 服务 |
| `ai_tracker_worker` | long_running | - | Celery Worker (4个并发) |
| `ai_tracker_beat` | long_running | - | Celery Beat 定时调度器 |
| `ai_tracker_feeder` | scheduled | 1h | RSS 巡航（每小时） |
| `ai_tracker_reporter` | scheduled | 每天 08:00 | 飞书日报推送 |
| `ai_tracker_reporter_weekly` | scheduled | 每周一 09:00 | 飞书周报推送 |
| `ai_tracker_rescue` | scheduled | 30m | 僵尸任务救援（每30分钟） |
| `ai_tracker_mcp` | long_running | - | MCP Server |

## 管理脚本用法

```bash
cd ~/.openclaw/workspace/ai_tracker_system

# 列出所有服务及状态
./manage.sh list

# 部署全部服务
./manage.sh deploy

# 部署单个服务
./manage.sh deploy ai_tracker_server

# 查看单个服务详细状态
./manage.sh status ai_tracker_feeder

# 查看服务日志（实时）
./manage.sh logs ai_tracker_feeder

# 查看最近 100 行日志
./manage.sh logs ai_tracker_feeder 100

# 重启服务
./manage.sh restart ai_tracker_server

# 停止服务
./manage.sh stop ai_tracker_server

# 启动服务
./manage.sh start ai_tracker_server

# 卸载单个服务
./manage.sh uninstall ai_tracker_feeder

# 卸载全部服务
./manage.sh uninstall

# 启用开机自启
./manage.sh enable ai_tracker_server

# 禁用开机自启
./manage.sh disable ai_tracker_server
```

## 服务配置

服务定义在 `services.json` 文件中：

```json
{
  "_meta": {
    "project_path": "/home/kangchen/.openclaw/workspace/ai_tracker_system",
    "venv_path": "/home/kangchen/.openclaw/workspace/ai_tracker_system/.venv/bin/python3"
  },
  "services": [
    {
      "id": "ai_tracker_feeder",
      "name": "AI Tracker RSS 巡航",
      "type": "scheduled",
      "executor": "python",
      "script": "auto_feeder.py",
      "schedule": {
        "type": "interval",
        "interval": "1h",
        "random_delay": "5m"
      }
    }
  ]
}
```

### 配置字段说明

| 字段 | 说明 |
|------|------|
| `id` | 服务唯一标识 |
| `name` | 服务显示名称 |
| `type` | `long_running`（常驻）或 `scheduled`（定时） |
| `executor` | 执行器类型：`python`/`celery`/`uvicorn` |
| `script` | Python 脚本路径（executor 为 python 时） |
| `args` | 命令行参数 |
| `schedule.type` | 调度类型：`interval`（间隔）或 `cron`（定时） |
| `schedule.interval` | 间隔，如 `1h`、`30m` |
| `schedule.oncalendar` | systemd OnCalendar 格式，如 `*-*-* 08:00:00` |
| `schedule.random_delay` | 随机延迟，避免同时触发 |
| `restart` | 重启策略：`always`、`on-failure` |

### 添加新服务

1. 编辑 `services.json`，在 `services` 数组中添加新服务定义
2. 运行 `./manage.sh deploy <service_id>` 部署新服务

示例 - 添加一个新的定时任务：

```json
{
  "id": "ai_tracker_backup",
  "name": "AI Tracker 数据库备份",
  "type": "scheduled",
  "executor": "python",
  "script": "backup.py",
  "schedule": {
    "type": "interval",
    "interval": "6h",
    "random_delay": "10m"
  }
}
```

## systemd 单元文件

部署后会自动在 `~/.config/systemd/user/` 目录下生成单元文件：

- `ai_tracker_<service_id>.service` - 服务单元
- `ai_tracker_<service_id>.timer` - 定时器单元（仅 scheduled 类型）

### 手动管理（不使用 manage.sh）

```bash
# 重新加载 systemd
systemctl --user daemon-reload

# 启动服务
systemctl --user start ai_tracker_server.service

# 查看状态
systemctl --user status ai_tracker_server.service

# 启用开机自启
systemctl --user enable ai_tracker_server.service

# 查看日志
journalctl --user -u ai_tracker_server.service -f
```

## 常见问题

### Q: 服务部署后如何确认是否运行？

```bash
# 方法1：使用管理脚本
./manage.sh list

# 方法2：检查进程
ps aux | grep server.py

# 方法3：检查 systemd
systemctl --user status ai_tracker_server.service
```

### Q: 如何查看服务日志？

```bash
# 实时日志
./manage.sh logs ai_tracker_feeder

# 最近 200 行
./manage.sh logs ai_tracker_feeder 200

# 使用 journalctl
journalctl --user -u ai_tracker_feeder.service -f
```

### Q: 服务启动失败怎么办？

1. 检查服务配置是否正确
2. 检查 Python 环境和依赖是否安装
3. 查看详细错误日志：
   ```bash
   journalctl --user -u ai_tracker_feeder.service -n 50
   ```

### Q: 如何修改定时任务的调度时间？

1. 编辑 `services.json` 中的 `schedule` 字段
2. 重新部署服务：
   ```bash
   ./manage.sh uninstall <service_id>
   ./manage.sh deploy <service_id>
   ```

## 安全说明

- systemd user services 运行在用户级别，无需 root 权限
- 服务配置和单元文件存储在用户目录
- 日志由 journald 管理，不会产生额外日志文件
