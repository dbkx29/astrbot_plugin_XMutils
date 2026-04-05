from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

from xmhelp import help_msg

class XMutils(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """插件初始化方法"""

    @filter.command("xmhelp")
    async def xmhelp(self, event: AstrMessageEvent):

        message_chain = event.get_messages() # 用户所发的消息的消息链 # from astrbot.api.message_components import *
        logger.info(message_chain)
        yield event.plain_result(help_msg)

    async def terminate(self):
        """插件销毁方法"""