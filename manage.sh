#!/usr/bin/env bash
# =============================================================================
# AI Tracker System - 服务管理脚本
# 统一管理所有 systemd service + timer
# 用法:
#   ./manage.sh deploy [service_id]   # 部署服务（默认部署全部）
#   ./manage.sh uninstall [service_id]  # 卸载服务（默认全部）
#   ./manage.sh status [service_id]    # 查看状态（默认全部）
#   ./manage.sh logs [service_id]      # 查看日志（默认查看最新）
#   ./manage.sh start [service_id]     # 启动服务
#   ./manage.sh stop [service_id]      # 停止服务
#   ./manage.sh restart [service_id]   # 重启服务
#   ./manage.sh list                   # 列出所有服务
#   ./manage.sh enable [service_id]    # 启用开机自启
#   ./manage.sh disable [service_id]   # 禁用开机自启
# =============================================================================

set -e

# 配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/services.json" ]]; then
    CONFIG_FILE="${SCRIPT_DIR}/services.json"
elif [[ -f "${SCRIPT_DIR}/systemd/services.json" ]]; then
    CONFIG_FILE="${SCRIPT_DIR}/systemd/services.json"
else
    CONFIG_FILE=""
fi
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
SERVICE_PREFIX="ai_tracker"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_jq() {
    if ! command -v jq &> /dev/null; then
        log_error "jq 未安装，请运行: sudo apt install jq"
        exit 1
    fi
}

read_config() {
    check_jq
    if [[ -z "$CONFIG_FILE" || ! -f "$CONFIG_FILE" ]]; then
        log_error "配置文件不存在: $CONFIG_FILE"
        exit 1
    fi
}

get_project_path() {
    jq -r '._meta.project_path' "$CONFIG_FILE"
}

get_venv_python() {
    jq -r '._meta.venv_path // (.project_path + "/.venv/bin/python3")' "$CONFIG_FILE"
}

get_service_ids() {
    jq -r '.services[].id' "$CONFIG_FILE"
}

get_service() {
    local service_id="$1"
    jq -c ".services[] | select(.id == \"$service_id\")" "$CONFIG_FILE"
}

is_python_script() {
    local executor="$1"
    [[ "$executor" == "python" || "$executor" == "python3" || "$executor" == *.py ]]
}

# cron 表达式转换为 systemd OnCalendar 格式
cron_to_oncalendar() {
    local cron_expr="$1"
    local minute=$(echo "$cron_expr" | awk '{print $1}')
    local hour=$(echo "$cron_expr" | awk '{print $2}')
    local day=$(echo "$cron_expr" | awk '{print $3}')
    local month=$(echo "$cron_expr" | awk '{print $4}')
    local weekday=$(echo "$cron_expr" | awk '{print $5}')

    local time_str=$(printf "%02d:%02d:00" "$hour" "$minute")

    local dow_str=""
    if [[ "$weekday" != "*" ]]; then
        local days=("Mon" "Tue" "Wed" "Thu" "Fri" "Sat" "Sun")
        local idx=$((weekday - 1))
        if [[ $idx -ge 0 && $idx -lt 7 ]]; then
            dow_str="${days[$idx]} "
        fi
    fi

    local day_str="*-${month}-${day}"
    if [[ "$day" == "*" ]]; then
        day_str="*"
    elif [[ "$month" == "*" ]]; then
        day_str="*-*"
    fi

    echo "${dow_str}${day_str} ${time_str}"
}

generate_service_unit() {
    local service_id="$1"
    local service_config="$2"

    local name=$(jq -r '.name // empty' <<< "$service_config")
    local executor=$(jq -r '.executor // empty' <<< "$service_config")
    local script=$(jq -r '.script // empty' <<< "$service_config")
    local args=$(jq -r '.args | if type == "array" then join(" ") else . end // ""' <<< "$service_config")
    local working_dir=$(jq -r '.working_dir // ._meta.project_path' "$CONFIG_FILE")
    local restart=$(jq -r '.restart // "always"' <<< "$service_config")
    local restart_sec=$(jq -r '.restart_sec // 10' <<< "$service_config")
    local venv_python=$(get_venv_python)

    local exec_start=""
    if [[ -n "$script" ]]; then
        exec_start="${venv_python} ${working_dir}/${script} ${args}"
    elif is_python_script "$executor"; then
        exec_start="${venv_python} ${executor} ${args}"
    else
        exec_start="${executor} ${args}"
    fi

    exec_start=$(echo "$exec_start" | xargs)

    cat <<UNITEOF
[Unit]
Description=${name}
After=network.target

[Service]
Type=simple
WorkingDirectory=${working_dir}
Environment=PATH=$(dirname "$venv_python"):/usr/local/bin:/usr/bin:/bin
Environment=PROJECT_PATH=${working_dir}
ExecStart=${exec_start}
Restart=${restart}
RestartSec=${restart_sec}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNITEOF
}

generate_timer_unit() {
    local service_id="$1"
    local service_config="$2"

    local name=$(jq -r '.name // empty' <<< "$service_config")
    local schedule_type=$(jq -r '.schedule.type // "interval"' <<< "$service_config")
    local interval=$(jq -r '.schedule.interval // "1h"' <<< "$service_config")
    local cron=$(jq -r '.schedule.cron // ""' <<< "$service_config")
    local random_delay=$(jq -r '.schedule.random_delay // "0"' <<< "$service_config")
    local schedule_desc=$(jq -r '.schedule.description // ""' <<< "$service_config")

    local timer_content=""

    if [[ "$schedule_type" == "interval" ]]; then
        local interval_value=$(echo "$interval" | grep -oE '[0-9]+')
        local interval_unit=$(echo "$interval" | grep -oE '[a-z]+')

        timer_content="[Unit]
Description=${name} Timer ${schedule_desc}

[Timer]
OnBootSec=5min
OnUnitActiveSec=${interval_value}${interval_unit}"
        if [[ "$random_delay" != "0" && "$random_delay" != "0m" ]]; then
            local delay_value=$(echo "$random_delay" | grep -oE '[0-9]+')
            local delay_unit=$(echo "$random_delay" | grep -oE '[a-z]+')
            timer_content="${timer_content}
RandomizedDelaySec=${delay_value}${delay_unit}"
        fi

    elif [[ "$schedule_type" == "cron" ]]; then
        # 优先使用 oncalendar 字段，否则转换 cron 表达式
        local oncalendar=$(jq -r '.schedule.oncalendar // ""' <<< "$service_config")
        if [[ -z "$oncalendar" ]]; then
            oncalendar=$(cron_to_oncalendar "$cron")
        fi
        timer_content="[Unit]
Description=${name} Timer ${schedule_desc}

[Timer]
OnCalendar=${oncalendar}
Persistent=true"
        if [[ "$random_delay" != "0" && "$random_delay" != "0m" ]]; then
            local delay_value=$(echo "$random_delay" | grep -oE '[0-9]+')
            local delay_unit=$(echo "$random_delay" | grep -oE '[a-z]+')
            timer_content="${timer_content}
RandomizedDelaySec=${delay_value}${delay_unit}"
        fi
    fi

    timer_content="${timer_content}

[Install]
WantedBy=timers.target"

    echo "$timer_content"
}

deploy_service() {
    local service_id="$1"
    local service_config=$(get_service "$service_id")

    if [[ -z "$service_config" ]]; then
        log_error "服务不存在: $service_id"
        return 1
    fi

    local service_type=$(jq -r '.type' <<< "$service_config")

    log_info "部署服务: $service_id (类型: $service_type)"

    mkdir -p "$SYSTEMD_USER_DIR"

    local service_unit=$(generate_service_unit "$service_id" "$service_config")
    echo "$service_unit" > "${SYSTEMD_USER_DIR}/${SERVICE_PREFIX}_${service_id}.service"
    log_success "创建 service: ${SERVICE_PREFIX}_${service_id}.service"

    if [[ "$service_type" == "scheduled" ]]; then
        local timer_unit=$(generate_timer_unit "$service_id" "$service_config")
        echo "$timer_unit" > "${SYSTEMD_USER_DIR}/${SERVICE_PREFIX}_${service_id}.timer"
        log_success "创建 timer: ${SERVICE_PREFIX}_${service_id}.timer"

        systemctl --user daemon-reload
        systemctl --user enable "${SERVICE_PREFIX}_${service_id}.timer"
        systemctl --user start "${SERVICE_PREFIX}_${service_id}.timer"
        log_success "已启用并启动定时器: ${SERVICE_PREFIX}_${service_id}.timer"
    else
        systemctl --user daemon-reload
        systemctl --user enable "${SERVICE_PREFIX}_${service_id}.service"
        systemctl --user start "${SERVICE_PREFIX}_${service_id}.service"
        log_success "已启用并启动服务: ${SERVICE_PREFIX}_${service_id}.service"
    fi
}

uninstall_service() {
    local service_id="$1"
    local service_config=$(get_service "$service_id")

    if [[ -z "$service_config" ]]; then
        log_error "服务不存在: $service_id"
        return 1
    fi

    local service_type=$(jq -r '.type' <<< "$service_config")

    log_info "卸载服务: $service_id"

    if [[ "$service_type" == "scheduled" ]]; then
        systemctl --user stop "${SERVICE_PREFIX}_${service_id}.timer" 2>/dev/null || true
        systemctl --user disable "${SERVICE_PREFIX}_${service_id}.timer" 2>/dev/null || true
        rm -f "${SYSTEMD_USER_DIR}/${SERVICE_PREFIX}_${service_id}.timer"
        log_success "移除 timer: ${SERVICE_PREFIX}_${service_id}.timer"
    else
        systemctl --user stop "${SERVICE_PREFIX}_${service_id}.service" 2>/dev/null || true
        systemctl --user disable "${SERVICE_PREFIX}_${service_id}.service" 2>/dev/null || true
        rm -f "${SYSTEMD_USER_DIR}/${SERVICE_PREFIX}_${service_id}.service"
        log_success "移除 service: ${SERVICE_PREFIX}_${service_id}.service"
    fi

    systemctl --user daemon-reload
    log_success "卸载完成: $service_id"
}

status_service() {
    local service_id="$1"
    local service_config=$(get_service "$service_id")

    if [[ -z "$service_config" ]]; then
        log_error "服务不存在: $service_id"
        return 1
    fi

    local service_type=$(jq -r '.type' <<< "$service_config")
    local name=$(jq -r '.name' <<< "$service_config")

    echo ""
    echo -e "${BLUE}=== ${name} (${service_id}) ===${NC}"

    if [[ "$service_type" == "scheduled" ]]; then
        echo -e "${YELLOW}类型:${NC} 定时任务"
        echo -e "${YELLOW}调度:${NC} $(jq -r '.schedule | tojson' <<< "$service_config")"

        echo ""
        echo -e "${YELLOW}Timer 状态:${NC}"
        systemctl --user status "${SERVICE_PREFIX}_${service_id}.timer" --no-pager 2>/dev/null || log_warn "Timer 未部署"

        echo ""
        echo -e "${YELLOW}最近运行记录:${NC}"
        journalctl --user -u "${SERVICE_PREFIX}_${service_id}.service" -n 5 --no-pager 2>/dev/null || log_warn "无运行记录"
    else
        echo -e "${YELLOW}类型:${NC} 长期运行服务"
        echo ""
        systemctl --user status "${SERVICE_PREFIX}_${service_id}.service" --no-pager 2>/dev/null || log_warn "服务未部署"
    fi
    echo ""
}

logs_service() {
    local service_id="$1"
    local lines="${2:-50}"

    if [[ ! -f "${SYSTEMD_USER_DIR}/${SERVICE_PREFIX}_${service_id}.service" ]]; then
        log_error "服务未部署: $service_id"
        return 1
    fi

    journalctl --user -u "${SERVICE_PREFIX}_${service_id}.service" -n "$lines" --no-pager -f
}

start_service() {
    local service_id="$1"
    local service_config=$(get_service "$service_id")
    local service_type=$(jq -r '.type' <<< "$service_config")

    if [[ "$service_type" == "scheduled" ]]; then
        systemctl --user start "${SERVICE_PREFIX}_${service_id}.timer"
        log_success "启动定时器: ${SERVICE_PREFIX}_${service_id}.timer"
    else
        systemctl --user start "${SERVICE_PREFIX}_${service_id}.service"
        log_success "启动服务: ${SERVICE_PREFIX}_${service_id}.service"
    fi
}

stop_service() {
    local service_id="$1"
    local service_config=$(get_service "$service_id")
    local service_type=$(jq -r '.type' <<< "$service_config")

    if [[ "$service_type" == "scheduled" ]]; then
        systemctl --user stop "${SERVICE_PREFIX}_${service_id}.timer"
        log_success "停止定时器: ${SERVICE_PREFIX}_${service_id}.timer"
    else
        systemctl --user stop "${SERVICE_PREFIX}_${service_id}.service"
        log_success "停止服务: ${SERVICE_PREFIX}_${service_id}.service"
    fi
}

restart_service() {
    local service_id="$1"
    local service_config=$(get_service "$service_id")
    local service_type=$(jq -r '.type' <<< "$service_config")

    if [[ "$service_type" == "scheduled" ]]; then
        systemctl --user restart "${SERVICE_PREFIX}_${service_id}.timer"
        log_success "重启定时器: ${SERVICE_PREFIX}_${service_id}.timer"
    else
        systemctl --user restart "${SERVICE_PREFIX}_${service_id}.service"
        log_success "重启服务: ${SERVICE_PREFIX}_${service_id}.service"
    fi
}

enable_service() {
    local service_id="$1"
    local service_config=$(get_service "$service_id")
    local service_type=$(jq -r '.type' <<< "$service_config")

    if [[ "$service_type" == "scheduled" ]]; then
        systemctl --user enable "${SERVICE_PREFIX}_${service_id}.timer"
        log_success "启用开机自启: ${SERVICE_PREFIX}_${service_id}.timer"
    else
        systemctl --user enable "${SERVICE_PREFIX}_${service_id}.service"
        log_success "启用开机自启: ${SERVICE_PREFIX}_${service_id}.service"
    fi
}

disable_service() {
    local service_id="$1"
    local service_config=$(get_service "$service_id")
    local service_type=$(jq -r '.type' <<< "$service_config")

    if [[ "$service_type" == "scheduled" ]]; then
        systemctl --user disable "${SERVICE_PREFIX}_${service_id}.timer"
        log_success "禁用开机自启: ${SERVICE_PREFIX}_${service_id}.timer"
    else
        systemctl --user disable "${SERVICE_PREFIX}_${service_id}.service"
        log_success "禁用开机自启: ${SERVICE_PREFIX}_${service_id}.service"
    fi
}

list_services() {
    echo ""
    echo -e "${BLUE}=== AI Tracker System 服务列表 ===${NC}"
    echo ""

    local project_name=$(jq -r '._meta.project_name' "$CONFIG_FILE")
    local project_path=$(jq -r '._meta.project_path' "$CONFIG_FILE")

    echo -e "${YELLOW}项目:${NC} $project_name"
    echo -e "${YELLOW}路径:${NC} $project_path"
    echo ""

    printf "%-35s %-12s %-18s %s\n" "服务ID" "类型" "调度" "名称"
    printf "%-35s %-12s %-18s %s\n" "-----------------------------------" "------------" "------------------" "----"

    while IFS= read -r service_id; do
        local service_config=$(get_service "$service_id")
        local name=$(jq -r '.name' <<< "$service_config")
        local service_type=$(jq -r '.type' <<< "$service_config")
        local schedule=""
        if [[ "$service_type" == "scheduled" ]]; then
            local sched_type=$(jq -r '.schedule.type' <<< "$service_config")
            if [[ "$sched_type" == "interval" ]]; then
                schedule=$(jq -r '.schedule.interval' <<< "$service_config")
            else
                schedule=$(jq -r '.schedule.cron' <<< "$service_config")
            fi
        else
            schedule="long-running"
        fi

        local status_symbol="○"
        local status_color="$NC"
        if [[ "$service_type" == "scheduled" ]]; then
            if systemctl --user is-active "${SERVICE_PREFIX}_${service_id}.timer" &>/dev/null; then
                status_symbol="●"
                status_color="$GREEN"
            fi
        else
            if systemctl --user is-active "${SERVICE_PREFIX}_${service_id}.service" &>/dev/null; then
                status_symbol="●"
                status_color="$GREEN"
            fi
        fi

        printf "%-35s ${status_color}%-12s${NC} %-18s %s\n" "$service_id" "$service_type" "$schedule" "$name"
        printf "   ${status_color}%s${NC}\n" "$status_symbol"

    done < <(get_service_ids)

    echo ""
    echo -e "${GREEN}●${NC} 运行中  ${RED}○${NC} 已停止"
    echo ""
}

deploy_all() {
    log_info "开始部署所有服务..."
    echo ""

    while IFS= read -r service_id; do
        deploy_service "$service_id" || log_warn "服务 $service_id 部署失败"
        echo ""
    done < <(get_service_ids)

    echo ""
    log_success "所有服务部署完成！"
    log_info "运行 './manage.sh list' 查看服务状态"
}

uninstall_all() {
    log_warn "即将卸载所有服务..."
    while IFS= read -r service_id; do
        uninstall_service "$service_id"
    done < <(get_service_ids)

    log_success "所有服务已卸载"
}

show_help() {
    cat <<EOF
AI Tracker System 服务管理脚本

用法:
    ./manage.sh <命令> [服务ID]

命令:
    deploy [id]      部署服务（默认全部）
    uninstall [id]   卸载服务（默认全部）
    status [id]     查看状态（默认全部）
    logs [id] [n]   查看最近 n 行日志（默认50行）
    start [id]      启动服务
    stop [id]       停止服务
    restart [id]    重启服务
    enable [id]     启用开机自启
    disable [id]    禁用开机自启
    list            列出所有服务

示例:
    ./manage.sh list                    # 列出所有服务
    ./manage.sh deploy                   # 部署全部服务
    ./manage.sh deploy ai_tracker_feeder # 只部署 RSS 巡航服务
    ./manage.sh status ai_tracker_server # 查看 API 服务状态
    ./manage.sh logs ai_tracker_worker 50# 查看 worker 最近50行日志
    ./manage.sh restart ai_tracker_feeder# 重启 RSS 巡航服务

配置文件: ${CONFIG_FILE}
EOF
}

main() {
    read_config

    local command="${1:-}"
    local service_id="${2:-}"
    local extra_arg="${3:-}"

    case "$command" in
        deploy)
            if [[ -z "$service_id" ]]; then
                deploy_all
            else
                deploy_service "$service_id"
            fi
            ;;
        uninstall)
            if [[ -z "$service_id" ]]; then
                uninstall_all
            else
                uninstall_service "$service_id"
            fi
            ;;
        status)
            if [[ -z "$service_id" ]]; then
                list_services
            else
                status_service "$service_id"
            fi
            ;;
        logs)
            if [[ -z "$service_id" ]]; then
                log_error "请指定服务ID"
                exit 1
            fi
            logs_service "$service_id" "$extra_arg"
            ;;
        start)
            if [[ -z "$service_id" ]]; then
                log_error "请指定服务ID"
                exit 1
            fi
            start_service "$service_id"
            ;;
        stop)
            if [[ -z "$service_id" ]]; then
                log_error "请指定服务ID"
                exit 1
            fi
            stop_service "$service_id"
            ;;
        restart)
            if [[ -z "$service_id" ]]; then
                log_error "请指定服务ID"
                exit 1
            fi
            restart_service "$service_id"
            ;;
        enable)
            if [[ -z "$service_id" ]]; then
                log_error "请指定服务ID"
                exit 1
            fi
            enable_service "$service_id"
            ;;
        disable)
            if [[ -z "$service_id" ]]; then
                log_error "请指定服务ID"
                exit 1
            fi
            disable_service "$service_id"
            ;;
        list)
            list_services
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            log_error "未知命令: $command"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

main "$@"
