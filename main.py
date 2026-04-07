from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from datetime import date
import random

class XMutils(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @staticmethod
    def luck_simple(num):
        res = ""
        if num == 100:
            res = '吉星高照'
        elif num >= 90:
            res = '鸿运当头'
        elif num >= 70:
            res = '好运相随'
        elif num >= 50:
            res = '一帆风顺'
        elif num >= 30:
            res = '风平浪静'
        elif num >= 10:
            res = '一波三折'
        elif num > 1:
            res = '诸事不顺'
        else:
            res = '厄运缠身'
        return [res, int(num/10+1)]

    async def initialize(self):
        """插件初始化方法"""

    @filter.command("xmhelp")
    async def xmhelp(self, event: AstrMessageEvent):
        help_msg = (
            "-----筱鸣壹形β食用说明-----\n"
            "[xmhelp]用于呼出此说明\n"
            "[xmjrrp]用于查看今日人品\n"
            "[xmsetu]用于获取随机涩图\n"
            "[b站视频链接]b站视频解析\n"
            "[摸/膜/吃/捅/@昵称]对指定用户做出指定行为\n"
            "[xmeat]觅食成贤\n"
            "[xmdice (\d+)d(\d+)]\n骰子\n"
            "[xmtp]台风信息\n"
            "\n+++++++已弃用+++++++\n"
            "[xmds]\ndeepseek对话(2025/2/6 new!!!!!)\n"
            "---祝您使用愉快2023/8/2---"
            "---祝您使用愉快2026/4/5---"
        )
        message_chain = event.get_messages() # 用户所发的消息的消息链 # from astrbot.api.message_components import *
        logger.info(message_chain)
        yield event.plain_result(help_msg)
        
    @filter.command("xmjrrp")
    async def xmjrrp(self, event: AstrMessageEvent):
        qid = event.message_obj.sender # 获取用户id
        
        rnd = random.Random()
        rnd.seed(int(date.today().strftime("%y%m%d")) + int(qid))
        lucknum = rnd.randint(1, 100)
        
        res = self.luck_simple(lucknum)[0]
        msg = f"您今日的幸运指数是{lucknum}/100,为{res}."
        
        yield event.plain_result(msg)

    async def terminate(self):
        """插件销毁方法"""