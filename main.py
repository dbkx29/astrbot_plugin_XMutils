from datetime import date
import random
import re

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star


class XMutils(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @staticmethod
    def parse_dice_expressions(incantation: str):
        expression = str(incantation).strip()
        if not expression:
            return []

        normalized = expression.replace("\uFF0C", ",")
        normalized = re.sub(r"[\s,+]+", " ", normalized).strip()
        if not normalized:
            return []

        parts = normalized.split(" ")
        parsed = []
        for part in parts:
            match = re.fullmatch(r"(\d+)d(\d+)", part)
            if not match:
                return None
            parsed.append((int(match.group(1)), int(match.group(2))))
        return parsed

    @staticmethod
    def roll_dice(num: int, dice: int):
        rolls = [random.randint(1, dice) for _ in range(num)]
        rolls.sort()
        return sum(rolls), rolls

    @staticmethod
    def luck_simple(num):
        res = ""
        if num == 100:
            res = "吉星高照"
        elif num >= 90:
            res = "鸿运当头"
        elif num >= 70:
            res = "好运相随"
        elif num >= 50:
            res = "一帆风顺"
        elif num >= 30:
            res = "风平浪静"
        elif num >= 10:
            res = "一波三折"
        elif num > 1:
            res = "诸事不顺"
        else:
            res = "厄运缠身"
        return [res, int(num / 10 + 1)]

    async def initialize(self):
        """插件初始化方法"""

    @filter.command("xmhelp")
    async def xmhelp(self, event: AstrMessageEvent):
        help_msg = (
            "-----小明工具插件说明-----\n"
            "[xmhelp] 用于呼出这份说明\n"
            "[xmjrrp] 用于查看今日人品\n"
            "[xmdice 3d6 2d10] 掷骰，支持空格、+、中英文逗号和换行分隔多个骰式\n"
        )
        message_chain = event.get_messages()
        logger.info(message_chain)
        yield event.plain_result(help_msg)

    @filter.command("xmjrrp")
    async def xmjrrp(self, event: AstrMessageEvent):
        qid = event.message_obj.sender.user_id

        rnd = random.Random()
        rnd.seed(int(date.today().strftime("%y%m%d")) + int(qid))
        lucknum = rnd.randint(1, 100)

        res = self.luck_simple(lucknum)[0]
        msg = f"您今日的幸运指数是 {lucknum}/100，{res}。"

        yield event.plain_result(msg)

    @filter.command("xmdice")
    async def xmdice(self, event: AstrMessageEvent, incantation: str):
        result = self.parse_dice_expressions(incantation)
        if result is None or not result:
            yield event.plain_result("InvalidUserInputException")
            return

        total_sum = 0
        parts = []
        for num, dice in result:
            if num > 233 or dice > 114514:
                yield event.plain_result("InvalidUserInputException")
                return

            subtotal, rolls = self.roll_dice(num, dice)
            total_sum += subtotal
            parts.append(f"{subtotal}({'+'.join(str(item) for item in rolls)})")

        send_msg = f"{total_sum}=" + "+".join(parts)

        from astrbot.api.message_components import Node, Plain

        node = Node(
            uin=2485981440,
            name="骰娘",
            content=[
                Plain(send_msg),
            ],
        )
        yield event.chain_result([node])

    async def terminate(self):
        """插件销毁方法"""
