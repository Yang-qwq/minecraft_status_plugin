# -*- coding: utf-8 -*-
from ncatbot.core import GroupMessage, BaseMessage, PrivateMessage
from ncatbot.plugin import BasePlugin, CompatibleEnrollment
from ncatbot.utils.logger import get_log
import shlex
import mcping
from typing import Tuple, Optional, Dict, Any
import re

bot = CompatibleEnrollment  # 兼容回调函数注册器
_log = get_log("minecraft_status_plugin")  # 日志记录器


class MineCraftStatusPlugin(BasePlugin):
    name = "MinecraftStatusPlugin"  # 插件名
    version = "0.0.2"  # 插件版本

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
        description = await self.transform_describe_message(status['description'])
        return (
            f"服务器 {server_name} ({ip}:{port}) 状态：在线\n"
            f"在线玩家：{status['players']['online']}/{status['players']['max']}\n"
            f"版本：{status['version']['name']}({status['version']['protocol']})\n"
            f"{description}\n"
        )

    async def query_single_server(self, ip: str, port: int, server_name: str = None) -> str:
        """
        查询单个服务器状态
        :param ip: 服务器IP
        :param port: 服务器端口
        :param server_name: 服务器名称（可选）
        :return: 状态信息字符串
        """
        try:
            status = await self.get_server_status(ip, port)
            _log.debug(f"获取服务器 {ip}:{port} 状态成功")

            display_name = server_name or f"{ip}:{port}"
            return await self.format_server_status(display_name, ip, port, status)

        except mcping.exceptions.ServerTimeoutError:
            _log.warning(f"连接到 {ip}:{port} 时超时")
            return f"服务器 {server_name or ip}:{port} 状态：超时\n"
        except mcping.exceptions.InvalidResponseError:
            _log.warning(f"连接到 {ip}:{port} 时响应无效")
            return f"服务器 {server_name or ip}:{port} 状态：响应无效\n"
        except Exception as e:
            _log.error(f"查询服务器 {ip}:{port} 时发生错误: {e}")
            return f"服务器 {server_name or ip}:{port} 状态：查询失败\n"

    async def query_group_servers(self, group_id: int) -> str:
        """
        查询群组绑定的所有服务器状态
        :param group_id: 群组ID
        :return: 状态信息字符串
        """
        if group_id not in self.data['data']['monitor_servers']:
            return "当前群组没有绑定任何Minecraft服务器。请使用 /mcadd 命令添加服务器。"

        servers = self.data['data']['monitor_servers'][group_id]
        if not servers:
            return "当前群组没有绑定任何Minecraft服务器。请使用 /mcadd 命令添加服务器。"

        response_parts = []
        server_names = list(servers.keys())

        for i, (server_name, server_address) in enumerate(servers.items()):
            try:
                ip, port = self.parse_server_address(server_address)
            except ValueError:
                response_parts.append(f"服务器 {server_name} 地址格式错误: {server_address}")
                continue

            status_info = await self.query_single_server(ip, port, server_name)
            response_parts.append(status_info)

            # 如果不是最后一个服务器，添加分隔符
            if i < len(server_names) - 1:
                response_parts.append("=" * 20 + "\n")

        return ''.join(response_parts)

    async def handle_status_command(self, event: BaseMessage | GroupMessage | PrivateMessage, command: list) -> None:
        """
        处理 /mcs 命令
        :param event: 消息事件
        :param command: 解析后的命令列表
        """
        if len(command) == 1:
            # 查询群组绑定的服务器
            response = await self.query_group_servers(event.group_id)
        else:
            # 查询指定服务器
            try:
                ip, port = self.parse_server_address(command[1])
                response = await self.query_single_server(ip, port)
            except ValueError as e:
                await event.reply_text(f"错误: {e}")
                return

        await event.reply_text(response)

    async def handle_add_command(self, event: BaseMessage | GroupMessage | PrivateMessage, command: list) -> None:
        """
        处理 /mcadd 命令
        :param event: 消息事件
        :param command: 解析后的命令列表
        """
        if len(command) < 3:
            await event.reply_text("请提供服务器名称和地址。格式：/mcadd <服务器名称> <ip:port> [群组ID]")
            return

        server_name = command[1]
        server_address = command[2]
        group_id = int(command[3]) if len(command) > 3 else event.group_id

        # 验证服务器名称
        if not self.validate_server_name(server_name):
            await event.reply_text("服务器名称只能包含字母、数字、下划线和连字符。")
            return

        # 验证服务器地址
        try:
            self.parse_server_address(server_address)
        except ValueError as e:
            await event.reply_text(f"错误: {e}")
            return

        # 更新配置
        if group_id not in self.data['data']['monitor_servers']:
            self.data['data']['monitor_servers'][group_id] = {}

        if server_name in self.data['data']['monitor_servers'][group_id]:
            await event.reply_text(f"服务器 {server_name} 已经在群组 {group_id} 的监控列表中。")
            return

        # 添加服务器到监控列表
        self.data['data']['monitor_servers'][group_id][server_name] = server_address
        await event.reply_text(f"已添加服务器 {server_name} ({server_address}) 到群组 {group_id} 的监控列表。")

    async def handle_delete_command(self, event: BaseMessage | GroupMessage | PrivateMessage, command: list) -> None:
        """
        处理 /mcdel 命令
        :param event: 消息事件
        :param command: 解析后的命令列表
        """
        if len(command) < 2:
            await event.reply_text("请提供要删除的服务器名称。格式：/mcdel <服务器名称> [群组ID]")
            return

        server_name = command[1]
        group_id = int(command[2]) if len(command) > 2 else event.group_id

        if group_id not in self.data['data']['monitor_servers']:
            await event.reply_text(f"群组 {group_id} 没有绑定任何Minecraft服务器。")
            return

        if server_name in self.data['data']['monitor_servers'][group_id]:
            # 删除指定服务器
            del self.data['data']['monitor_servers'][group_id][server_name]
            await event.reply_text(f"已删除群组 {group_id} 中的服务器 {server_name}。")
        else:
            await event.reply_text(f"群组 {group_id} 中没有名为 {server_name} 的服务器。")

    async def handle_list_command(self, event: BaseMessage | GroupMessage | PrivateMessage, command: list) -> None:
        """
        处理 /mclist 命令
        :param event: 消息事件
        :param command: 解析后的命令列表
        """
        group_id = int(command[1]) if len(command) > 1 else event.group_id

        if group_id not in self.data['data']['monitor_servers'] or not self.data['data']['monitor_servers'][group_id]:
            await event.reply_text(f"群组 {group_id} 没有绑定任何Minecraft服务器。")
            return

        servers = self.data['data']['monitor_servers'][group_id]
        response = f"群组 {group_id} 绑定的服务器列表：\n"
        for server_name, server_address in servers.items():
            response += f"- {server_name}: {server_address}\n"

        await event.reply_text(response)

    async def handle_help_command(self, event: BaseMessage | GroupMessage | PrivateMessage) -> None:
        """
        处理 /mchelp 命令
        :param event: 消息事件
        """
        await event.reply_text("""Minecraft服务器状态查询插件帮助：

命令列表：
/mcs [ip:port] - 查询服务器状态（不指定则查询群组绑定的服务器）
/mcadd <名称> <ip:port> [群组ID] - 添加服务器到群组监控列表
/mcdel <名称> [群组ID] - 从群组监控列表中删除服务器
/mclist [群组ID] - 显示群组绑定的服务器列表
/mchelp - 显示此帮助信息

示例：
/mcs mc.example.com:25565
/mcadd MyServer mc.example.com:25565
/mcdel MyServer
/mclist""")

    async def scheduler_monitor_server_status(self, ip: str, port: int):
        """定时监控Minecraft服务器状态
        :param ip: 服务器IP地址
        :param port: 服务器端口
        """
        # TODO: 实现定时监控功能
        pass

    async def command_handler(self, event: BaseMessage | GroupMessage | PrivateMessage):
        """插件命令的解析器

        :param event: 消息事件
        :return: None
        """
        # 替换消息中的转义符，如\\n -> \n
        replaced_message = event.raw_message.replace("\\n", "\n")

        # 解析命令
        try:
            command = shlex.split(replaced_message)
        except ValueError:
            await event.reply_text("命令格式错误，请检查引号是否匹配。")
            return

        if not command:
            return

        # 命令分发
        try:
            if command[0] == '/mcs':
                await self.handle_status_command(event, command)
            elif command[0] == '/mcadd':
                await self.handle_add_command(event, command)
            elif command[0] == '/mcdel':
                await self.handle_delete_command(event, command)
            elif command[0] == '/mclist':
                await self.handle_list_command(event, command)
            elif command[0] == '/mchelp':
                await self.handle_help_command(event)
            else:
                await event.reply_text("未知命令。使用 /mchelp 查看帮助。")
        except Exception as e:
            _log.error(f"处理命令时发生错误: {e}")
            await event.reply_text("处理命令时发生错误，请稍后重试。")

    async def on_load(self):
        """插件加载时的初始化"""
        # 创建持久化数据结构
        if 'data' not in self.data:
            self.data['data'] = {}

        if 'monitor_servers' not in self.data['data']:
            self.data['data']['monitor_servers'] = {}

        # 注册命令处理器
        self.register_user_func(
            "命令事件处理器",
            self.command_handler,
            description="处理插件命令（如/mcs）",
            usage="/mcs [ip:[port]]",
            regex='^/mc(s|add|del|list|watch|help)',
            examples=[
                "/mcs my.server.com:25565",  # 查询指定服务器状态
                "/mcadd MyServer my.server.com:25565",
                "/mcadd MyServer my.server.com:25565 123456789",  # 可选的群组ID
                "/mcdel MyServer",  # 删除指定服务器
                "/mcdel MyServer 123456789",  # 删除指定服务器，指定群组ID
                "/mclist",  # 列出群组绑定的服务器
                "/mchelp"  # 显示帮助信息
            ]
        )
