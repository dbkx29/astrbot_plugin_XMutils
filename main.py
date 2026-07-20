from datetime import date, datetime, timedelta
import random
import re

import requests

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

    @staticmethod
    def resolve_sender_id(event: AstrMessageEvent) -> int:
        candidates = [
            getattr(event, "self_id", None),
            getattr(getattr(event, "message_obj", None), "self_id", None),
            getattr(getattr(event, "bot", None), "self_id", None),
        ]
        for candidate in candidates:
            if candidate is None:
                continue
            try:
                return int(candidate)
            except (TypeError, ValueError):
                continue
        return 2485981440

    @staticmethod
    def fetch_storm_messages(self_id: int):
        from astrbot.api.message_components import Node, Plain

        current_time = datetime.utcnow()
        query_time = (
            f"{current_time.year}-{current_time.month:02d}-{current_time.day:02d}"
            f"T{current_time.hour:02d}:00Z"
        )
        list_url = f"https://zoom.earth/data/storms/?date={query_time}&to=12"
        headers = {
            "User-Agent": "XMutils/1.0",
            "Accept": "*/*",
            "Connection": "keep-alive",
        }

        response = requests.get(list_url, headers=headers, timeout=15.05)
        response.raise_for_status()
        storm_ids = response.json().get("storms", [])

        messages = []
        for storm_id in storm_ids:
            storm_url = f"https://zoom.earth/data/storms/?id={storm_id}&lang=zh"
            storm_response = requests.get(storm_url, headers=headers, timeout=15.05)
            storm_response.raise_for_status()
            storm = storm_response.json()

            agencies = storm.get("agencies", "")
            if isinstance(agencies, list):
                agencies = "、".join(str(item) for item in agencies)

            content_lines = [
                f"{storm.get('title', storm_id)}, 数据提供机构:{agencies}, 位置:{storm.get('place', '未知')}",
            ]

            latest_forecast = next(
                (track for track in storm.get("track", []) if track.get("forecast") is True),
                None,
            )
            if latest_forecast:
                content_lines.extend(
                    [
                        "最新预测:",
                        f"时间:{latest_forecast.get('date', '未知')}",
                        f"风速:{latest_forecast.get('wind', '未知')}km/h",
                        f"描述:{latest_forecast.get('description', '暂无描述')}",
                        f"https://zoom.earth/storms/{storm.get('id', storm_id)}/#overlays=wind",
                    ]
                )
            else:
                content_lines.append("暂无可用预测数据")

            messages.append(
                Node(
                    uin=int(self_id),
                    name="鸣卫贰@筱鸣壹形β",
                    content=[Plain("\n".join(content_lines))],
                )
            )

        return messages

    @staticmethod
    def find_latest_radar_url():
        current_time = datetime.now()
        minute = (current_time.minute // 6) * 6
        utc_time = datetime.utcnow().replace(minute=minute, second=0, microsecond=0)

        for _ in range(40):
            url = (
                f"https://image.nmc.cn/product/{utc_time:%Y}/{utc_time:%m}/{utc_time:%d}/RDCP/"
                f"SEVP_AOC_RDCP_SLDAS3_ECREF_AECN_L88_PI_{utc_time:%Y%m%d%H%M}00000.PNG"
            )
            response = requests.get(url, allow_redirects=True, timeout=15.05)
            if response.status_code == 200:
                return url
            utc_time -= timedelta(minutes=6)

        raise RuntimeError("未找到可用的华东雷达图")

    async def initialize(self):
        """插件初始化方法"""

    @filter.command("xmhelp")
    @filter.command("help")
    async def xmhelp(self, event: AstrMessageEvent):
        help_msg = (
            "-----小明工具插件说明-----\n"
            "[xmhelp] 用于呼出这份说明\n"
            "[xmjrrp] 用于查看今日人品\n"
            "[xmdice 3d6 2d10] 掷骰，支持空格、+、中英文逗号和换行分隔多个骰式\n"
            "[xmtp] 台风信息\n"
            "[xmrd] 华东雷达图\n"
        )
        logger.info(event.get_messages())
        yield event.plain_result(help_msg)

    @filter.command("xmjrrp")
    @filter.command("jrrp")
    async def xmjrrp(self, event: AstrMessageEvent):
        qid = event.message_obj.sender.user_id

        rnd = random.Random()
        rnd.seed(int(date.today().strftime("%y%m%d")) + int(qid))
        lucknum = rnd.randint(1, 100)

        res = self.luck_simple(lucknum)[0]
        msg = f"您今日的幸运指数是 {lucknum}/100，{res}。"
        yield event.plain_result(msg)

    @filter.command("xmdice")
    @filter.command("dice")
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

        from astrbot.api.message_components import Node, Plain

        node = Node(
            uin=self.resolve_sender_id(event),
            name="骰娘",
            content=[Plain(f"{total_sum}=" + "+".join(parts))],
        )
        yield event.chain_result([node])

    @filter.command("tp")
    async def xmtp(self, event: AstrMessageEvent):
        try:
            messages = self.fetch_storm_messages(self.resolve_sender_id(event))
        except Exception as exc:
            logger.exception("Failed to fetch storm data")
            yield event.plain_result(f"获取台风信息失败: {exc}")
            return

        if not messages:
            yield event.plain_result("当前暂无台风数据。")
            return

        yield event.chain_result(messages)

    @filter.command("rd")
    async def xmrd(self, event: AstrMessageEvent):
        try:
            radar_url = self.find_latest_radar_url()
        except Exception as exc:
            logger.exception("Failed to fetch radar image")
            yield event.plain_result(f"获取华东雷达图失败: {exc}")
            return

        from astrbot.api.message_components import Image, Plain

        yield event.chain_result(
            [
                Plain("https://www.nmc.cn/publish/radar/huadong.html\n"),
                Image.fromURL(radar_url),
            ]
        )

    async def terminate(self):
        """插件销毁方法"""
