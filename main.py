# -*- coding: utf-8 -*-
import os
import re
import sqlite3
import datetime
from typing import Any, Dict, Tuple, List, Optional
import matplotlib

matplotlib.use('Agg')  # 使用非交互式后端，适合服务器环境
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import mcping
from ncatbot.plugin import BasePlugin, CompatibleEnrollment
from ncatbot.utils.logger import get_log

from .command_handler import MinecraftCommandHandlerMixin

bot = CompatibleEnrollment  # 兼容回调函数注册器
_log = get_log("minecraft_status_plugin")  # 日志记录器


class MinecraftStatusPlugin(MinecraftCommandHandlerMixin, BasePlugin):
    name = "MinecraftStatusPlugin"  # 插件名
    version = "0.0.5"  # 插件版本

    def init_database_connection(self):
        """初始化数据库连接"""
        try:
            # 确保数据库目录存在
            db_dir = os.path.dirname(self.db_path)
            if not os.path.exists(db_dir):
                os.makedirs(db_dir)

            # 创建数据库连接
            self.sqlite_conn = sqlite3.connect(
                self.db_path,
                timeout=30.0,  # 设置超时
                check_same_thread=False  # 允许多线程访问
            )

            # 启用WAL模式提高并发性能
            self.sqlite_conn.execute("PRAGMA journal_mode=WAL")
            self.sqlite_conn.execute("PRAGMA synchronous=NORMAL")
            self.sqlite_conn.execute("PRAGMA cache_size=10000")
            self.sqlite_conn.execute("PRAGMA temp_store=MEMORY")

            _log.info("数据库连接初始化成功")

        except Exception as e:
            _log.error(f"数据库连接初始化失败: {e}")
            self.sqlite_conn = None
            raise sqlite3.Error(f"数据库连接初始化失败: {e}")

    def ensure_connection(self):
        """确保数据库连接有效"""
        try:
            if self.sqlite_conn is None:
                self.init_database_connection()
                return

            # 测试连接是否有效
            self.sqlite_conn.execute("SELECT 1")

        except sqlite3.Error:
            _log.warning("数据库连接已断开，重新建立连接")
            try:
                if self.sqlite_conn:
                    self.sqlite_conn.close()
            except:
                _log.debug("关闭旧数据库连接时发生错误")
            self.init_database_connection()

    def init_database(self):
        """初始化数据库，创建必要的表格和索引

        :return: None
        """
        try:
            # 确保连接有效
            self.ensure_connection()

            cursor = self.sqlite_conn.cursor()

            # 创建服务器状态历史表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS server_status_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    server_ip TEXT NOT NULL,
                    server_port INTEGER NOT NULL,
                    online_players INTEGER,
                    response_time REAL,
                    status TEXT DEFAULT 'online',
                    error_message TEXT
                )
            ''')

            # 创建索引优化查询性能
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_server_time 
                ON server_status_history(server_ip, server_port, timestamp)
            ''')

            # 单独的时间索引，方便按时间范围查询
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON server_status_history(timestamp)
            ''')

            self.sqlite_conn.commit()
            _log.info("数据库初始化成功")

        except Exception as e:
            _log.error(f"数据库初始化失败: {e}")
            raise sqlite3.Error(f"数据库初始化失败: {e}")

    async def save_server_status(self, ip: str, port: int,
                                 status: Dict[str, Any], response_time: float = None,
                                 error_message: str = None):
        """保存服务器状态到数据库

        :param ip: 服务器IP地址
        :param port: 服务器端口
        :param status: 服务器状态字典
        :param response_time: 响应时间（毫秒）
        :param error_message: 错误信息（可选）
        :return: None
        """
        try:
            # 确保连接有效
            self.ensure_connection()

            cursor = self.sqlite_conn.cursor()

            # 解析状态信息
            players = status.get('players', {}) if status else {}
            online_players = players.get('online', 0) if players else None

            # 插入历史记录到server_status_history表（改进结构）
            cursor.execute('''
                INSERT INTO server_status_history 
                (timestamp, server_ip, server_port, online_players, response_time, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.datetime.now(),
                ip,
                port,
                online_players,
                response_time,
                'online' if status else 'offline',
                error_message
            ))

            self.sqlite_conn.commit()
            _log.debug(f"已保存服务器 {ip}:{port} 的状态记录")

        except Exception as e:
            _log.error(f"保存服务器状态失败: {e}")
            # 如果连接出错，尝试重新建立连接
            try:
                self.ensure_connection()
            except:
                pass

    async def save_server_offline_status(self, ip: str, port: int, response_time: float = None,
                                         error_message: str = None):
        """保存服务器离线状态到数据库

        :param ip: 服务器IP地址
        :param port: 服务器端口
        :param response_time: 响应时间（毫秒，可选）
        :param error_message: 错误信息（可选）
        :return: None
        """
        try:
            # 确保连接有效
            self.ensure_connection()

            cursor = self.sqlite_conn.cursor()

            # 插入离线状态记录（使用改进的表结构）
            cursor.execute('''
                INSERT INTO server_status_history 
                (timestamp, server_ip, server_port, online_players, response_time, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.datetime.now(),
                ip,
                port,
                None,
                response_time,
                'offline',
                error_message
            ))

            self.sqlite_conn.commit()
            _log.debug(f"已保存服务器 {ip}:{port} 的离线状态记录")

        except Exception as e:
            _log.error(f"保存服务器离线状态失败: {e}")
            # 如果连接出错，尝试重新建立连接
            try:
                self.ensure_connection()
            except:
                pass

    async def get_server_history(self, ip: str, port: int, hours: int = 24) -> List[Dict]:
        """获取服务器的历史状态数据

        :param ip: 服务器IP地址
        :param port: 服务器端口
        :param hours: 查询的小时数，默认为24小时
        :return: 历史数据列表
        """
        try:
            # 确保连接有效
            self.ensure_connection()

            cursor = self.sqlite_conn.cursor()

            # 获取指定时间范围内的历史数据
            time_limit = datetime.datetime.now() - datetime.timedelta(hours=hours)

            cursor.execute('''
                SELECT timestamp, online_players, response_time, status, error_message
                FROM server_status_history
                WHERE server_ip = ? AND server_port = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            ''', (ip, port, time_limit))

            rows = cursor.fetchall()

            history = []
            for row in rows:
                history.append({
                    'timestamp': datetime.datetime.fromisoformat(row[0]),
                    'online_players': row[1],
                    'is_online': row[1] is not None and row[3] == 'online',
                    'response_time': row[2],
                    'status': row[3],
                    'error_message': row[4]
                })

            return history

        except Exception as e:
            _log.error(f"获取服务器历史数据失败: {e}")
            # 如果连接出错，尝试重新建立连接
            try:
                self.ensure_connection()
            except:
                pass
            return []

    async def cleanup_old_data(self, days: int = 30) -> int:
        """清理旧数据

        :param days: 保留最近多少天的数据，默认30天
        :return: 清理的记录数量
        """
        try:
            # 确保连接有效
            self.ensure_connection()

            cursor = self.sqlite_conn.cursor()

            # 计算截止日期
            cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days)

            # 先查询要删除的记录数量
            cursor.execute('''
                SELECT COUNT(*) FROM server_status_history 
                WHERE timestamp < ?
            ''', (cutoff_date,))

            count_to_delete = cursor.fetchone()[0]

            if count_to_delete == 0:
                _log.info(f"没有超过 {days} 天的旧数据需要清理")
                return 0

            # 执行删除操作
            cursor.execute('''
                DELETE FROM server_status_history 
                WHERE timestamp < ?
            ''', (cutoff_date,))

            deleted_count = cursor.rowcount
            self.sqlite_conn.commit()

            _log.info(f"成功清理了 {deleted_count} 条超过 {days} 天的历史记录")
            return deleted_count

        except Exception as e:
            _log.error(f"清理旧数据失败: {e}")
            # 如果连接出错，尝试重新建立连接
            try:
                self.ensure_connection()
            except:
                pass
            return 0

    async def get_database_stats(self) -> Dict[str, Any]:
        """获取数据库统计信息

        :return: 数据库统计信息字典
        """
        try:
            # 确保连接有效
            self.ensure_connection()

            cursor = self.sqlite_conn.cursor()

            # 获取总记录数
            cursor.execute("SELECT COUNT(*) FROM server_status_history")
            total_records = cursor.fetchone()[0]

            # 获取最早的记录时间
            cursor.execute("SELECT MIN(timestamp) FROM server_status_history")
            earliest_record = cursor.fetchone()[0]

            # 获取最新的记录时间
            cursor.execute("SELECT MAX(timestamp) FROM server_status_history")
            latest_record = cursor.fetchone()[0]

            # 获取数据库文件大小
            db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0

            return {
                'total_records': total_records,
                'earliest_record': earliest_record,
                'latest_record': latest_record,
                'database_size_bytes': db_size,
                'database_size_mb': round(db_size / (1024 * 1024), 2)
            }

        except Exception as e:
            _log.error(f"获取数据库统计信息失败: {e}")
            return {}

    async def generate_status_chart(self, server_name: str, ip: str, port: int, hours: int = 24) -> Optional[str]:
        """生成服务器状态图表"""
        try:
            # 设置常用的中文字体，优先兼容 Linux 上的 CJK 字体
            font_list = [
                "Noto Sans CJK SC",       # Linux 常见无衬线中文
                "Noto Serif CJK SC",      # Linux 常见衬线中文
                "Noto Sans Mono CJK SC",  # Linux 常见等宽中文
                "WenQuanYi Zen Hei",      # Linux 文泉驿正黑
                "WenQuanYi Micro Hei",    # Linux 文泉驿微米黑（部分发行版）
                "Microsoft YaHei",        # Windows 微软雅黑
                "SimHei",                 # Windows 黑体
                "PingFang SC",            # macOS 苹方
                "STHeiti",                # macOS 华文黑体（旧系统）
                "Arial Unicode MS",       # 通用 Unicode 覆盖
                "Arial",                  # 英文
                "sans-serif"
            ]
            matplotlib.rcParams['font.sans-serif'] = font_list
            matplotlib.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

            history = await self.get_server_history(ip, port, hours)
            if not history:
                return None

            # 创建图表（增加第三个子图用于在线/离线饼图）
            fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 12))
            fig.suptitle(f'服务器 {server_name} 状态监控 ({hours}小时)', fontsize=14)

            # 准备数据
            timestamps = [h['timestamp'] for h in history]
            online_players = [h['online_players'] if h['online_players'] is not None else 0 for h in history]
            response_times = [h['response_time'] for h in history if h['response_time'] is not None]
            response_timestamps = [h['timestamp'] for h in history if h['response_time'] is not None]

            # 玩家数量图表
            ax1.plot(timestamps, online_players, 'b-', label='在线玩家', linewidth=2)
            ax1.fill_between(timestamps, online_players, alpha=0.3, color='blue')
            ax1.set_ylabel('玩家数量')
            ax1.set_title('在线玩家数量变化')
            ax1.legend()
            ax1.grid(True, alpha=0.3)

            # 响应时间图表
            if response_times:
                ax2.plot(response_timestamps, response_times, 'g-', label='响应时间', linewidth=2)
                ax2.set_ylabel('响应时间 (ms)')
                ax2.set_title('服务器响应时间')
                ax2.legend()
                ax2.grid(True, alpha=0.3)
            else:
                ax2.text(0.5, 0.5, '无响应时间数据', ha='center', va='center', transform=ax2.transAxes)
                ax2.set_title('服务器响应时间')

            # 在线/离线饼图
            online_count = sum(1 for h in history if h.get('is_online'))
            offline_count = len(history) - online_count
            labels = ['在线', '离线']
            sizes = [online_count, offline_count]
            colors = ['#4CAF50', '#F44336']
            if online_count + offline_count > 0:
                ax3.pie(
                    sizes,
                    labels=labels,
                    autopct='%1.1f%%',
                    startangle=90,
                    colors=colors,
                    textprops={'color': 'black'}
                )
                ax3.axis('equal')
            else:
                ax3.text(0.5, 0.5, '无在线/离线数据', ha='center', va='center', transform=ax3.transAxes)
            ax3.set_title('在线/离线占比')

            # 格式化x轴时间（仅对折线图适用）
            for ax in [ax1, ax2]:
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=max(1, hours // 6)))
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

            plt.tight_layout()

            # 保存图表
            chart_path = self.work_space.path.as_posix() + "/charts/" + f"{server_name}_{ip}_{port}_status.png"
            plt.savefig(chart_path, dpi=150, bbox_inches='tight')
            plt.close()

            return chart_path

        except Exception as e:
            _log.error(f"生成状态图表失败: {e}")
            return None

    async def monitor_all_servers(self):
        """监控所有启用的服务器，避免重复查询"""
        try:
            # 从内存配置中获取所有启用的监控服务器
            unique_servers = set()

            # 遍历所有群组的绑定服务器
            for group_id, servers in self.data['data']['bind_servers'].items():
                for server_name, server_address in servers.items():
                    # 检查是否启用了监控
                    if self.data['data']['monitor_servers'].get(server_address, False):
                        try:
                            ip, port = self.parse_server_address(server_address)
                            unique_servers.add((ip, port))
                        except ValueError:
                            _log.warning(f"服务器 {server_name} 地址格式错误: {server_address}")

            # 只查询一次每个唯一的服务器
            for ip, port in unique_servers:
                try:
                    start_time = datetime.datetime.now()
                    status = await self.get_server_status(ip, port)
                    end_time = datetime.datetime.now()

                    response_time = (end_time - start_time).total_seconds() * 1000  # 转换为毫秒

                    # 保存状态到数据库
                    await self.save_server_status(ip, port, status, response_time)

                    _log.debug(f"监控服务器 {ip}:{port} 成功")

                except Exception as e:
                    _log.warning(f"监控服务器 {ip}:{port} 失败: {e}")
                    # 保存离线状态，包含错误信息
                    await self.save_server_offline_status(ip, port, error_message=str(e))

        except Exception as e:
            _log.error(f"监控服务器时发生错误: {e}")

    @staticmethod
    async def transform_describe_message(message: dict, markdown_format: bool = False) -> str:
        """
        将Minecraft服务器描述信息（motd）从JSON格式转换为字符串。
        支持可选的markdown格式（加粗、斜体、下划线等）。
        """

        def apply_format(_text: str, bold: bool = False, italic: bool = False, underlined: bool = False,
                         strikethrough: bool = False) -> str:
            """
            应用文本格式
            :param _text: 要格式化的文本
            :param bold: 是否加粗
            :param italic: 是否斜体
            :param underlined: 是否下划线
            :param strikethrough: 是否删除线
            :return: 格式化后的文本
            """
            # 仅在markdown_format为True时应用格式
            if not markdown_format:
                return _text
            # Markdown格式
            if bold:
                _text = f"**{_text}**"
            if italic:
                _text = f"*{_text}*"
            if underlined:
                _text = f"<u>{_text}</u>"
            if strikethrough:
                _text = f"~~{_text}~~"
            return _text

        result = []
        # 兼容只有'text'字段的情况
        if 'extra' in message:
            for part in message['extra']:
                if isinstance(part, str):
                    # 如果是字符串，直接添加
                    result.append(part)
                    continue
                text = part.get('text', '')
                text = apply_format(
                    text,
                    part.get('bold', False),
                    part.get('italic', False),
                    part.get('underlined', False),
                    part.get('strikethrough', False)
                )
                result.append(text)
        if 'text' in message and message['text']:
            # 处理主text字段
            text = message['text']
            # 这里不处理格式
            result.append(text)
        return ''.join(result)

    @staticmethod
    async def get_server_status(ip: str, port: int) -> dict:
        """获取Minecraft服务器状态

        :param ip: 服务器IP地址
        :param port: 服务器端口
        :raises mcping.exceptions.ServerTimeoutError: 服务器连接超时
        :raises mcping.exceptions.InvalidResponseError: 服务器响应无效
        :raises mcping.exceptions.MCPingException: 其他MCPing异常
        :return: 服务器状态字典
        """
        return mcping.status(ip, port)

    @staticmethod
    def parse_server_address(address: str) -> Tuple[str, int]:
        """
        解析服务器地址
        :param address: 服务器地址，格式为 ip:port 或 ip
        :return: (ip, port) 元组
        """
        try:
            if ':' in address:
                ip, port = address.split(":")
                return ip, int(port)
            else:
                return address, 25565  # 默认端口
        except ValueError:
            raise ValueError(f"无效的服务器地址格式: {address}")

    @staticmethod
    def validate_server_name(name: str) -> bool:
        """
        验证服务器名称是否有效
        :param name: 服务器名称
        :return: 是否有效
        """
        # 服务器名称应该只包含字母、数字、下划线和连字符
        return bool(re.match(r'^[a-zA-Z0-9_-]+$', name))

    async def format_server_status(self, server_name: str, ip: str, port: int, status: Dict[str, Any]) -> str:
        """
        格式化服务器状态信息
        :param server_name: 服务器名称
        :param ip: 服务器IP
        :param port: 服务器端口
        :param status: 服务器状态字典
        :return: 格式化后的状态信息
        """
        # 获取玩家信息
        players = status.get('players', {})
        online_players = players.get('online', 0)
        max_players = players.get('max', 0)

        # 获取版本信息
        version_info = status.get('version', {})
        version_name = version_info.get('name', 'Unknown')
        protocol_version = version_info.get('protocol', 'Unknown')

        try:
            # 处理描述信息
            description_raw = status.get('description', None)

            if isinstance(description_raw, str):
                description = description_raw
            elif isinstance(description_raw, dict):
                # 如果描述是字典格式，转换为字符串
                description = await self.transform_describe_message(description_raw)
            else:
                # 如果描述是其他类型，记录警告并使用字符串表示
                _log.warning(f"未知的描述类型: {type(description_raw)}, 使用默认字符串表示")
                description = str(description_raw)

            return (
                f"服务器 {server_name} ({ip}:{port}) 状态：✅在线\n"
                f"在线玩家：{online_players}/{max_players}\n"
                f"版本：{version_name} ({protocol_version})\n"
                f"{description}\n"
            )

        except Exception as e:
            _log.error(f"格式化服务器状态时发生错误: {e}")
            return (
                f"服务器 {server_name} ({ip}:{port}) 状态：在线\n"
                f"在线玩家：{online_players}/{max_players}\n"
                f"版本：{version_name} ({protocol_version})\n"
                f"无法获取服务器描述信息\n"
            )

    async def query_single_server(self, ip: str, port: int, server_name: str = None) -> str:
        """
        查询单个服务器状态，优先从数据库获取，避免重复查询
        :param ip: 服务器IP
        :param port: 服务器端口
        :param server_name: 服务器名称（可选）
        :return: 状态信息字符串
        """
        display_name = server_name or f"{ip}:{port}"

        # 进行实时查询
        try:
            status = await self.get_server_status(ip, port)
            _log.debug(f"获取服务器 {ip}:{port} 状态成功")

            return await self.format_server_status(display_name, ip, port, status)
        except mcping.exceptions.ServerTimeoutError:
            _log.warning(f"发起查询 {ip}:{port} 时超时")
            return f"服务器 {display_name} ({ip}:{port}) 状态：❌超时\n"
        except mcping.exceptions.InvalidResponseError:
            _log.warning(f"发起查询 {ip}:{port} 时响应无效")
            return f"服务器 {display_name} ({ip}:{port}) 状态：⚠️响应无效\n"
        except Exception as e:
            _log.error(f"发起查询 {ip}:{port} 时发生错误: {e}")
            return f"服务器 {display_name} ({ip}:{port}) 状态：❌查询失败\n"

    async def query_group_servers(self, group_id: int) -> str:
        """
        查询群组绑定的所有服务器状态，优先使用数据库中的状态
        :param group_id: 群组ID
        :return: 状态信息字符串
        """
        if group_id not in self.data['data']['bind_servers']:
            return "当前群组没有绑定任何Minecraft服务器！\n请使用 /mcadd 命令添加服务器"

        servers = self.data['data']['bind_servers'][group_id]
        if not servers:
            return "当前群组没有绑定任何Minecraft服务器！\n请使用 /mcadd 命令添加服务器"

        response_parts = []
        server_names = list(servers.keys())

        for i, (server_name, server_address) in enumerate(servers.items()):
            try:
                ip, port = self.parse_server_address(server_address)
            except ValueError:
                _log.error(f"服务器 {server_name} 地址格式错误: {server_address}")
                response_parts.append(f"服务器 {server_name} 地址格式错误: {server_address}")
                continue

            status_info = await self.query_single_server(ip, port, server_name)
            response_parts.append(status_info)

            # 如果不是最后一个服务器，添加分隔符
            if i < len(server_names) - 1:
                response_parts.append("=" * 20 + "\n")

        return ''.join(response_parts)

    async def on_load(self):
        """插件加载时的初始化"""
        # 初始化文件结构
        if not os.path.exists(self.work_space.path.as_posix() + "/charts"):
            os.makedirs(self.work_space.path.as_posix() + "/charts")

        # 设置数据库路径
        self.db_path = self.work_space.path.as_posix() + "/server_history.db"

        # 初始化数据库连接
        self.sqlite_conn = None
        self.init_database_connection()

        # 初始化数据库
        self.init_database()

        # 注册配置项
        self.register_config("monitor_interval", 300, value_type="int", allowed_values=["int"],
                             description="定时监控服务器状态的间隔时间（秒）")
        self.register_config("mention_online_players_change", False, value_type="bool",
                             description="当在线玩家数量变化时是否发送消息通知")
        self.register_config("mention_server_status_change", False, value_type="bool",
                             description="当服务器状态变化时是否发送消息通知")

        # 创建持久化数据结构
        if 'data' not in self.data:
            self.data['data'] = {}

        if 'bind_servers' not in self.data['data']:
            self.data['data']['bind_servers'] = {}

        if 'monitor_servers' not in self.data['data']:
            self.data['data']['monitor_servers'] = {}

        # 注册监控任务
        self.add_scheduled_task(
            self.monitor_all_servers,
            "minecraft_monitor",
            self.config['monitor_interval'],  # 定时监控间隔
        )

        # 注册用户命令处理器
        self.register_user_func(
            "UserCommand",
            self.user_command_handler,
            description="查询服务器状态（实时数据）、显示服务器列表、生成图表、查看统计信息、查看所有监控服务器状态",
            usage="/mcs [ip:port]|/mclist [group_id]|/mchelp|/mcchart <name> [hours]|/mcstats <name> [hours]",
            regex='^/mc(s|list|help|chart|stats|status)',
            examples=[
                "/mcs my.server.com:25565",  # 查询指定服务器实时状态
                "/mcs",  # 查询群组绑定的服务器实时状态
                "/mclist",  # 列出群组绑定的服务器
                "/mclist 123456789",  # 列出指定群组绑定的服务器
                "/mchelp",  # 显示帮助信息
                "/mcchart MyServer",  # 生成24小时状态图表
                "/mcchart MyServer 48",  # 生成48小时状态图表
                "/mcstats MyServer",  # 查看24小时统计信息
                "/mcstats MyServer 72",  # 查看72小时统计信息
            ]
        )

        # 注册管理员命令处理器
        self.register_admin_func(
            "AdminCommand",
            self.admin_command_handler,
            description="添加/删除服务器到监控列表、管理监控状态、列出监控服务器、清理旧数据、生成图表、查看统计信息、查看所有监控服务器状态",
            usage="/mcadd <name> <ip:port> [group_id]|/mcdel <name> [group_id]|/mchelp-admin|/mcmonitor set <name> <on|off>|/mcmonitor list|/mcmonitor purge [days]",
            regex='^/mc(add|del|help-admin|monitor|chart|stats|status)',
            examples=[
                "/mcadd MyServer my.server.com:25565",  # 添加服务器到当前群组
                "/mcadd MyServer my.server.com:25565 123456789",  # 添加服务器到指定群组
                "/mcdel MyServer",  # 删除当前群组中的服务器
                "/mcdel MyServer 123456789",  # 删除指定群组中的服务器
                "/mchelp-admin",  # 显示管理员帮助信息
                "/mcmonitor set MyServer on",  # 启用服务器监控
                "/mcmonitor set MyServer off",  # 禁用服务器监控
                "/mcmonitor list",  # 列出正在监控的服务器
                "/mcmonitor purge 30",  # 清理30天前的旧数据
                "/mcchart MyServer 24",  # 生成24小时状态图表
                "/mcstats MyServer 48",  # 查看48小时统计信息
            ]
        )
        _log.info("Minecraft状态插件已加载")

    async def on_unload(self):
        """插件卸载时的清理工作"""
        try:
            if hasattr(self, 'sqlite_conn') and self.sqlite_conn:
                _log.info("正在关闭数据库连接...")
                self.sqlite_conn.close()
                self.sqlite_conn = None
                _log.info("数据库连接已关闭")
        except Exception as e:
            _log.error(f"关闭数据库连接时发生错误: {e}")

        _log.info("Minecraft状态插件已卸载")
