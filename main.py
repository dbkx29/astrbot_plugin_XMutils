from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register("xmhelp", "XMUtils", "筱鸣壹形功能帮助插件", "1.0.0")
class XmUtils(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """插件初始化方法"""

    @filter.command("xmhelp")
    async def xmhelp(self, event: AstrMessageEvent):
        """呼出筱鸣壹形帮助信息"""
        help_msg = (
            "-----筱鸣壹形β食用说明-----\n"
            "[xmds]\ndeepseek对话（25.2.6new）\n"
            "[xmhelp]\n用于呼出此说明\n"
            "[xmjrrp]\n用于查看今日人品\n"
            "[xmsetu]\n用于获取随机涩图\n"
            "[b站视频链接]\nb站视频解析\n"
            "[摸/膜/吃/捅/@昵称]\n对指定用户做出指定行为\n"
            "[xmeat]\n觅食成贤\n"
            "[xmdice (\d+)d(\d+)]\n骰子\n"
            "[xmtp]\n台风信息\n"
            "---祝您使用愉快2023/8/2---"
        )
        message_chain = event.get_messages() # 用户所发的消息的消息链 # from astrbot.api.message_components import *
        logger.info(message_chain)
        yield event.plain_result(help_msg)

    async def terminate(self):
        """插件销毁方法"""