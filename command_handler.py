# -*- coding: utf-8 -*-
import shlex
from ncatbot.core import BaseMessage, GroupMessage, PrivateMessage, MessageChain, Image
from ncatbot.utils.logger import get_log

_log = get_log("MinecraftStatusPlugin")


class MinecraftCommandHandlerMixin:
    """命令处理逻辑 Mixin，供 MinecraftStatusPlugin 继承使用。"""

    async def handle_chart_command(self, event: BaseMessage | GroupMessage | PrivateMessage, command: list) -> None:
        """处理 /mcchart 命令"""
        if len(command) < 2:
            await event.reply_text("请提供服务器名称\n格式：/mcchart <服务器名称> [小时数]")
            return

        server_name = command[1]
        hours = int(command[2]) if len(command) > 2 else 24

        # 检查是否为有效服务器
        group_id = event.group_id
        if group_id not in self.data['data']['bind_servers'] or server_name not in self.data['data']['bind_servers'][
            group_id]:
            await event.reply_text(f"服务器 {server_name} 不在当前群组的监控列表中")
            return

        # 检查服务器是否开启监控
        server_address = self.data['data']['bind_servers'][group_id][server_name]
        if not self.data['data']['monitor_servers'].get(server_address, False):
            await event.reply_text(f"服务器 {server_name} 未启用监控，无法获取统计信息")
            return

        await event.reply_text(f"正在生成服务器 {server_name} 的状态图表，请稍候...")

        try:
            ip, port = self.parse_server_address(server_address)
        except ValueError as e:
            await event.reply_text(f"服务器地址格式错误: {e}")
            return

        try:
            chart_path = await self.generate_status_chart(server_name, ip, port, hours)
            if chart_path:
                await event.reply(
                    rtf=MessageChain(
                        [f"服务器 {server_name} 的状态图表已生成，时间范围：{hours}小时", Image(chart_path)])
                )
            else:
                _log.warning(f"无法生成服务器 {server_name} 的状态图表")
                await event.reply_text(f"无法生成服务器 {server_name} 的状态图表，可能没有足够的历史数据")
        except Exception as e:
            await event.reply_text(f"生成图表时发生错误: {e}")


    async def handle_monitor_command(self, event: BaseMessage | GroupMessage | PrivateMessage, command: list) -> None:
        """处理 /mcmonitor 命令，支持 set 和 list 子命令

        :param event: 事件对象
        :param command: 命令参数列表
        :return: None
        """
        if len(command) < 2:
            await event.reply_text("请提供子命令！\n格式：/mcmonitor <set|list> [参数]")
            return

        subcommand = command[1].lower()

        if subcommand == 'set':
            await self.handle_monitor_set_command(event, command)
        elif subcommand == 'list':
            await self.handle_monitor_list_command(event)
        elif subcommand == 'purge':
            await self.handle_monitor_purge_command(event, command)
        else:
            await event.reply_text("无效的子命令！\n支持的命令：/mcmonitor <set|list|purge> [参数]")


    async def handle_monitor_set_command(self, event: BaseMessage | GroupMessage | PrivateMessage,
                                         command: list) -> None:
        """处理 /mcmonitor set 命令，启用或禁用服务器自动监控

        :param event: 事件对象
        :param command: 命令参数列表
        :return: None
        """
        if len(command) < 4:
            await event.reply_text("请提供服务器名称和监控状态\n格式：/mcmonitor set <服务器名称> <on|off>")
            return

        server_name = command[2]
        monitor_status = command[3].lower()

        if monitor_status not in ['on', 'off', 'true', 'false']:
            await event.reply_text("监控状态必须是 on/true 或 off/false")
            return

        group_id = event.group_id

        # 检查服务器是否在绑定列表中
        if group_id not in self.data['data']['bind_servers'] or server_name not in self.data['data']['bind_servers'][
            group_id]:
            await event.reply_text(f"服务器 {server_name} 不在当前群组的绑定列表中")
            return

        server_address = self.data['data']['bind_servers'][group_id][server_name]

        try:
            # 更新监控配置
            is_monitoring = monitor_status in ['on', 'true']

            # 如果不存在时尝试取消监控
            if self.data['data']['monitor_servers'].get(server_address) is None and not is_monitoring:
                _log.warning('尝试取消未绑定的服务器监控')
                return

            # 更新监控配置
            if is_monitoring:
                self.data['data']['monitor_servers'][server_address] = True
            else:
                self.data['data']['monitor_servers'][server_address] = False

            status_text = "启用" if is_monitoring else "禁用"
            await event.reply_text(f"已{status_text}服务器 {server_name} 的自动监控")

        except Exception as e:
            _log.error('更新监控配置失败', exc_info=e)
            await event.reply_text(f"更新监控配置时发生错误: {e}")


    async def handle_monitor_list_command(self, event: BaseMessage | GroupMessage | PrivateMessage) -> None:
        """处理 /mcmonitor list 命令，列出所有正在监控的服务器

        :param event: 事件对象
        :return: None
        """
        try:
            monitoring_servers = []

            # 遍历所有群组的绑定服务器，找出正在监控的服务器
            for group_id, servers in self.data['data']['bind_servers'].items():
                for server_name, server_address in servers.items():
                    if self.data['data']['monitor_servers'].get(server_address, False):
                        monitoring_servers.append({
                            'group_id': group_id,
                            'server_name': server_name,
                            'server_address': server_address
                        })

            if not monitoring_servers:
                await event.reply_text("当前没有正在监控的服务器")
                return

            # 构建回复消息
            response_parts = ["正在监控的服务器列表：\n"]

            for server_info in monitoring_servers:
                response_parts.append(
                    f"• {server_info['server_name']} ({server_info['server_address']}) - 群组 {server_info['group_id']}")

            response_parts.append(f"\n总计：{len(monitoring_servers)} 个服务器正在监控中")

            await event.reply_text('\n'.join(response_parts))

        except Exception as e:
            _log.error('获取监控服务器列表失败', exc_info=e)
            await event.reply_text(f"获取监控服务器列表时发生错误: {e}")


    async def handle_monitor_purge_command(self, event: BaseMessage | GroupMessage | PrivateMessage,
                                           command: list) -> None:
        """处理 /mcmonitor purge 命令，清理旧数据

        :param event: 事件对象
        :param command: 命令参数列表
        :return: None
        """
        try:
            # 解析参数
            if len(command) < 3:
                # 默认清理30天前的数据
                days = 30
            else:
                try:
                    days = int(command[2])
                    if days < 1:
                        await event.reply_text("保留天数必须大于0")
                        return
                    if days > 365:
                        await event.reply_text("保留天数不能超过365天")
                        return
                except ValueError:
                    await event.reply_text("保留天数必须是有效的数字")
                    return

            # 获取清理前的统计信息
            stats_before = await self.get_database_stats()

            if stats_before.get('total_records', 0) == 0:
                await event.reply_text("数据库中没有数据需要清理")
                return

            # 执行清理操作
            await event.reply_text(f"正在清理超过 {days} 天的旧数据，请稍候...")

            deleted_count = await self.cleanup_old_data(days)

            # 获取清理后的统计信息
            stats_after = await self.get_database_stats()

            # 构建回复消息
            response_parts = [
                f"✅ 数据清理完成！",
                f"",
                f"📊 清理统计：",
                f"• 清理记录数：{deleted_count} 条",
                f"• 清理前总记录：{stats_before.get('total_records', 0)} 条",
                f"• 清理后总记录：{stats_after.get('total_records', 0)} 条",
                f"• 数据库大小：{stats_after.get('database_size_mb', 0)} MB",
                f"",
                f"🗑️ 已删除超过 {days} 天的历史记录"
            ]

            if stats_after.get('earliest_record'):
                response_parts.append(f"📅 最早记录时间：{stats_after['earliest_record']}")

            await event.reply_text('\n'.join(response_parts))

        except Exception as e:
            _log.error('清理数据时发生错误', exc_info=e)
            await event.reply_text(f"清理数据时发生错误: {e}")


    async def handle_stats_command(self, event: BaseMessage | GroupMessage | PrivateMessage, command: list) -> None:
        """处理 /mcstats 命令"""
        if len(command) < 2:
            await event.reply_text("请提供服务器名称！\n格式：/mcstats <服务器名称> [小时数]")
            return

        server_name = command[1]
        hours = int(command[2]) if len(command) > 2 else 24
        group_id = event.group_id

        # 检查是否为有效服务器
        if group_id not in self.data['data']['bind_servers'] or server_name not in self.data['data']['bind_servers'][
            group_id]:
            await event.reply_text(f"服务器 {server_name} 不在当前群组的监控列表中")
            return

        # 检查服务器是否开启监控
        server_address = self.data['data']['bind_servers'][group_id][server_name]
        if not self.data['data']['monitor_servers'].get(server_address, False):
            await event.reply_text(f"服务器 {server_name} 未启用监控，无法获取统计信息")
            return

        try:
            ip, port = self.parse_server_address(server_address)
        except ValueError as e:
            await event.reply_text(f"服务器地址格式错误: {e}")
            return

        try:
            history = await self.get_server_history(ip, port, hours)
            if not history:
                await event.reply_text(f"服务器 {server_name} 没有找到历史数据")
                return

            # 计算统计信息
            total_records = len(history)
            online_records = sum(1 for h in history if h['is_online'])
            offline_records = total_records - online_records
            uptime_rate = (online_records / total_records * 100) if total_records > 0 else 0

            # 玩家数量统计
            online_players_list = [h['online_players'] for h in history if
                                   h['is_online'] and h['online_players'] is not None]
            if online_players_list:
                avg_players = sum(online_players_list) / len(online_players_list)
                max_players_ever = max(online_players_list)
                min_players_ever = min(online_players_list)
            else:
                avg_players = max_players_ever = min_players_ever = 0

            # 响应时间统计
            response_times = [h['response_time'] for h in history if h['response_time'] is not None]
            if response_times:
                avg_response = sum(response_times) / len(response_times)
                max_response = max(response_times)
                min_response = min(response_times)
            else:
                avg_response = max_response = min_response = 0

            stats_text = f"""服务器 {server_name} 统计信息 ({hours}小时):

    📊 基本统计:
    • 总记录数: {total_records}
    • 在线记录: {online_records}
    • 离线记录: {offline_records}
    • 在线率: {uptime_rate:.1f}%

    👥 玩家统计:
    • 平均在线玩家: {avg_players:.1f}
    • 最高在线玩家: {max_players_ever}
    • 最低在线玩家: {min_players_ever}

    ⚡ 性能统计:
    • 平均响应时间: {avg_response:.1f}ms
    • 最快响应时间: {min_response:.1f}ms
    • 最慢响应时间: {max_response:.1f}ms"""

            await event.reply_text(stats_text)

        except Exception as e:
            await event.reply_text(f"获取统计信息时发生错误: {e}")


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


    async def handle_list_command(self, event: BaseMessage | GroupMessage | PrivateMessage, command: list) -> None:
        """
        处理 /mclist 命令
        :param event: 消息事件
        :param command: 解析后的命令列表
        """
        group_id = int(command[1]) if len(command) > 1 else event.group_id

        if group_id not in self.data['data']['bind_servers'] or not self.data['data']['bind_servers'][group_id]:
            await event.reply_text(f"群组 {group_id} 没有绑定任何Minecraft服务器！")
            return

        servers = self.data['data']['bind_servers'][group_id]
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

    用户命令：
    /mcs [ip:port] - 查询服务器状态（不指定则查询群组绑定的服务器，获取实时数据）
    /mclist [群组ID] - 显示群组绑定的服务器列表
    /mchelp - 显示此帮助信息
    /mcchart <服务器名称> [小时数] - 生成服务器状态图表（默认24小时）
    /mcstats <服务器名称> [小时数] - 查看服务器统计信息（默认24小时）

    管理员命令：
    /mcadd <名称> <ip:port> [群组ID] - 添加服务器到群组监控列表
    /mcdel <名称> [群组ID] - 从群组监控列表中删除服务器
    /mcmonitor set <名称> <on|off> - 启用/禁用服务器自动监控
    /mcmonitor list - 列出所有正在监控的服务器
    /mcmonitor purge [天数] - 清理超过指定天数的旧数据（默认30天）

    示例：
    /mcs my.server.com:25565  # 查询指定服务器实时状态
    /mcs  # 查询群组绑定的服务器实时状态
    /mclist
    /mchelp
    /mcchart MyServer 48
    /mcstats MyServer 72
    """)


    async def user_command_handler(self, event: BaseMessage | GroupMessage | PrivateMessage):
        """处理用户命令事件"""
        # 替换消息中的转义符，如\\n -> \n
        replaced_message = event.raw_message.replace("\\n", "\n")

        # 解析命令
        try:
            command = shlex.split(replaced_message)
        except ValueError:
            await event.reply_text("命令格式错误，请检查引号是否匹配！")
            return

        if not command:
            return

        # 命令分发
        try:
            if command[0] == '/mcs':
                await self.handle_status_command(event, command)
            elif command[0] == '/mclist':
                await self.handle_list_command(event, command)
            elif command[0] == '/mchelp':
                await self.handle_help_command(event)
            elif command[0] == '/mcchart':
                await self.handle_chart_command(event, command)
            elif command[0] == '/mcstats':
                await self.handle_stats_command(event, command)
            else:
                # 不是我喜欢的命令，直接跳过
                return
        except Exception as e:
            _log.error(f"处理用户命令时发生错误: {e}")
            await event.reply_text("处理命令时发生错误，请稍后重试")


    async def handle_add_command(self, event: BaseMessage | GroupMessage | PrivateMessage, command: list) -> None:
        """
        处理 /mcadd 命令
        :param event: 消息事件
        :param command: 解析后的命令列表
        """
        if len(command) < 3:
            await event.reply_text("请提供服务器名称和地址！\n格式：/mcadd <服务器名称> <ip:port> [群组ID]")
            return

        server_name = command[1]
        server_address = command[2]
        group_id = int(command[3]) if len(command) > 3 else event.group_id

        # 验证服务器名称
        if not self.validate_server_name(server_name):
            await event.reply_text("服务器名称只能包含字母、数字、下划线和连字符")
            return

        # 验证服务器地址
        try:
            self.parse_server_address(server_address)
        except ValueError as e:
            await event.reply_text(f"错误: {e}")
            return

        # 更新配置
        if group_id not in self.data['data']['bind_servers']:
            self.data['data']['bind_servers'][group_id] = {}

        if server_name in self.data['data']['bind_servers'][group_id]:
            await event.reply_text(f"服务器 {server_name} 已经在群组 {group_id} 的监控列表中")
            return

        # 添加服务器到监控列表
        self.data['data']['bind_servers'][group_id][server_name] = server_address
        await event.reply_text(f"已添加服务器 {server_name} ({server_address}) 到群组 {group_id} 的监控列表")


    async def handle_delete_command(self, event: BaseMessage | GroupMessage | PrivateMessage, command: list) -> None:
        """
        处理 /mcdel 命令
        :param event: 消息事件
        :param command: 解析后的命令列表
        """
        if len(command) < 2:
            await event.reply_text("请提供要删除的服务器名称！\n格式：/mcdel <服务器名称> [群组ID]")
            return

        server_name = command[1]
        group_id = int(command[2]) if len(command) > 2 else event.group_id

        if group_id not in self.data['data']['bind_servers']:
            await event.reply_text(f"群组 {group_id} 没有绑定任何Minecraft服务器")
            return

        if server_name in self.data['data']['bind_servers'][group_id]:
            # 删除指定服务器
            del self.data['data']['bind_servers'][group_id][server_name]
            await event.reply_text(f"已删除群组 {group_id} 中的服务器 {server_name}")
        else:
            await event.reply_text(f"群组 {group_id} 中没有名为 {server_name} 的服务器")


    async def handle_admin_help_command(self, event: BaseMessage | GroupMessage | PrivateMessage) -> None:
        """
        处理管理员帮助命令
        :param event: 消息事件
        """
        await event.reply_text("""Minecraft服务器状态查询插件管理员命令帮助：

    /mcadd <名称> <ip:port> [群组ID] - 添加服务器到群组监控列表
    /mcdel <名称> [群组ID] - 从群组监控列表中删除服务器
    /mcmonitor set <名称> <on|off> - 启用/禁用服务器自动监控
    /mcmonitor list - 列出所有正在监控的服务器
    /mcmonitor purge [天数] - 清理超过指定天数的旧数据（默认30天）
    /mcchart <名称> [小时数] - 生成服务器状态图表
    /mcstats <名称> [小时数] - 查看服务器统计信息
    /mchelp-admin - 显示此帮助信息

    示例：
    /mcadd MyServer mc.example.com:25565
    /mcadd MyServer mc.example.com:25565 123456789
    /mcdel MyServer
    /mcdel MyServer 123456789
    /mcmonitor set MyServer on
    /mcmonitor set MyServer off
    /mcmonitor list
    /mcmonitor purge 30
    /mcchart MyServer 24
    /mcstats MyServer 48

    注意：这些命令仅限管理员使用，可以跨群组管理服务器
    配置修改请直接编辑配置文件或联系管理员""")


    async def admin_command_handler(self, event: BaseMessage | GroupMessage | PrivateMessage):
        """处理管理员命令事件"""
        # 替换消息中的转义符，如\\n -> \n
        replaced_message = event.raw_message.replace("\\n", "\n")

        # 解析命令
        try:
            command = shlex.split(replaced_message)
        except ValueError:
            await event.reply_text("命令格式错误，请检查引号是否匹配！")
            return

        if not command:
            return

        # 命令分发
        try:
            if command[0] == '/mcadd':
                await self.handle_add_command(event, command)
            elif command[0] == '/mcdel':
                await self.handle_delete_command(event, command)
            elif command[0] == '/mchelp-admin':
                await self.handle_admin_help_command(event)
            elif command[0] == '/mcmonitor':
                await self.handle_monitor_command(event, command)
            else:
                # 不是管理员命令，跳过处理
                return
        except Exception as e:
            _log.error(f"处理管理员命令时发生错误: {e}")
            await event.reply_text("处理命令时发生错误，请稍后重试")
