# -*- coding: utf-8 -*-
from ncatbot.core import GroupMessage, BaseMessage, PrivateMessage
from ncatbot.plugin import BasePlugin, CompatibleEnrollment
from ncatbot.utils.logger import get_log
import shlex
import mcping

bot = CompatibleEnrollment  # 兼容回调函数注册器
_log = get_log("minecraft_status_plugin")  # 日志记录器


class MineCraftStatusPlugin(BasePlugin):
    name = "MinecraftStatusPlugin"  # 插件名
    version = "0.0.1"  # 插件版本

    @staticmethod
    async def transform_describe_message(message: dict, markdown_format: bool = False) -> str:
        """
        将Minecraft服务器描述信息（motd）从JSON格式转换为字符串。
        支持可选的markdown格式（加粗、斜体、下划线等）。
        """
        def apply_format(text, bold, italic, underlined, strikethrough, color):
            # 仅在markdown_format为True时应用格式
            if not markdown_format:
                return text
            # Markdown格式
            if bold:
                text = f"**{text}**"
            if italic:
                text = f"*{text}*"
            if underlined:
                text = f"<u>{text}</u>"
            if strikethrough:
                text = f"~~{text}~~"
            # 颜色不直接支持，简单用代码块包裹
            # 你可以根据需要自定义颜色处理
            return text

        # 处理obfuscated（乱码）文本
        def obfuscate(text):
            # 简单实现：用*替换
            return ''.join('*' if c != '\n' else '\n' for c in text)

        result = []
        # 兼容只有'text'字段的情况
        if 'extra' in message:
            for part in message['extra']:
                text = part.get('text', '')
                if part.get('obfuscated', False):
                    text = obfuscate(text)
                text = apply_format(
                    text,
                    part.get('bold', False),
                    part.get('italic', False),
                    part.get('underlined', False),
                    part.get('strikethrough', False),
                    part.get('color', None)
                )
                result.append(text)
        if 'text' in message and message['text']:
            # 处理主text字段
            text = message['text']
            # 这里不处理格式
            result.append(text)
        return ''.join(result)

    # @staticmethod
    # async def transform_version_message(message: dict) -> str:
    #     """
    #     将Minecraft服务器版本信息从dict转换为字符串。
    #     """
    #     name = message.get('name', '')
    #     protocol = message.get('protocol', '')
    #     if name and protocol:
    #         return f"{name} (协议号: {protocol})"
    #     elif name:
    #         return name
    #     elif protocol:
    #         return f"协议号: {protocol}"
    #     else:
    #         return ""


    async def mcs_command_handler(self, event: BaseMessage | GroupMessage | PrivateMessage):
        """/mcs命令的解析器
        用法：/mcs <ip[:port]>

        :param event:
        :return:
        """
        # 替换消息中的转义符，如\\n -> \n
        replaced_message = event.raw_message.replace("\\n", "\n")

        # 解析命令
        command = shlex.split(replaced_message)

        # 检测命令长度
        if len(command) == 1:
            return
        else:
            try:
                ip, port = command[1].split(":")
            except ValueError:
                ip, port = command[1], 25565  # 默认端口为25565

        try:
            # 尝试获取服务器状态
            status = mcping.status(ip, int(port))
        except mcping.exceptions.ServerTimeoutError:
            # 服务器超时
            _log.error(f"连接到 {ip}:{port} 时超时")
            await event.reply_text(f"连接到 {ip}:{port} 时超时，请检查服务器是否在线。")
            return
        except mcping.exceptions.InvalidResponseError:
            # 响应无效
            _log.error(f"连接到 {ip}:{port} 时响应无效")
            await event.reply_text(f"连接到 {ip}:{port} 时响应无效，请检查服务器地址和端口是否正确。")
            return
        else:
            _log.info("获取服务器状态成功")
            await event.reply_text(
                f"服务器 {ip}:{port} 状态：\n"
                f"在线玩家：{status['players']['online']}/{status['players']['max']}\n"
                f"版本：{status['version']['name']}\n"
                f"MOTD：{await self.transform_describe_message(status['description'])}\n"
            )
            return

    async def on_load(self):
        # 注册命令处理器
        self.register_user_func("命令事件处理器(/mcs)", self.mcs_command_handler, prefix="/mcs")
