from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import asyncio
import io
import random
import re

import requests

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

RADAR_URL_TEMPLATE = (
    "https://image.nmc.cn/product/{t:%Y}/{t:%m}/{t:%d}/RDCP/"
    "SEVP_AOC_RDCP_SLDAS3_ECREF_AECN_L88_PI_{t:%Y%m%d%H%M}00000.PNG"
)
RADAR_FRAME_INTERVAL = 6  # 分钟，雷达图每 6 分钟一个时次
RADAR_FRAME_COUNT = 12  # 拼进 GIF 的帧数，12 帧约 1 小时
RADAR_NEWEST_LOOKBACK = 8  # 查找最新一帧时向前探测的时次数
RADAR_MAX_LOOKBACK = 48  # 收集帧时最多向前探测的时次数
RADAR_PROBE_WINDOW = 4  # 每轮并发探测的时次数
RADAR_GIF_WIDTH = 400  # GIF 缩放后的宽度，用于控制体积
RADAR_GIF_DURATION = 200  # 每帧播放时长（毫秒）
RADAR_GIF_MAX_BYTES = 3_500_000  # 超过该体积时进一步缩小
RADAR_DOWNLOAD_WORKERS = 8  # 并发下载雷达图的线程数
RADAR_REQUEST_TIMEOUT = 15.05
RADAR_HEADERS = {
    "User-Agent": "XMutils/1.0",
    "Accept": "*/*",
    "Connection": "keep-alive",
}
RADAR_TIMEZONE = timezone(timedelta(hours=8))


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
    def radar_url(at: datetime) -> str:
        return RADAR_URL_TEMPLATE.format(t=at)

    @classmethod
    def radar_slots(cls, count: int, newest: datetime | None = None):
        """返回从 newest（默认当前时间）开始、按时间倒序排列的 count 个雷达时次。"""
        newest = newest or datetime.now(timezone.utc)
        newest = newest.replace(
            minute=(newest.minute // RADAR_FRAME_INTERVAL) * RADAR_FRAME_INTERVAL,
            second=0,
            microsecond=0,
        )
        return [
            newest - timedelta(minutes=RADAR_FRAME_INTERVAL * index)
            for index in range(count)
        ]

    @classmethod
    def radar_slot_exists(cls, at: datetime):
        """探测某个时次的雷达图是否存在：True/False，网络异常时返回 None。"""
        try:
            response = requests.head(
                cls.radar_url(at), headers=RADAR_HEADERS, timeout=RADAR_REQUEST_TIMEOUT
            )
        except requests.RequestException:
            return None

        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        return None

    @classmethod
    def download_radar_slot(cls, at: datetime):
        """下载某个时次的雷达图，失败时返回 None。"""
        try:
            response = requests.get(
                cls.radar_url(at), headers=RADAR_HEADERS, timeout=RADAR_REQUEST_TIMEOUT
            )
        except requests.RequestException:
            return None

        if response.status_code != 200 or len(response.content) < 5000:
            return None
        return at, response.content

    @classmethod
    def collect_radar_frames(cls, frame_count: int = RADAR_FRAME_COUNT):
        """从最近的时次往前收集 frame_count 张可用的雷达图，按时间正序返回 (时间, 图片字节)。"""
        newest = None
        for at in cls.radar_slots(RADAR_NEWEST_LOOKBACK):
            if cls.radar_slot_exists(at) is not False:
                newest = at
                break
        if newest is None:
            raise RuntimeError("最近几个小时没有可用的华东雷达图")

        frames = []
        slots = cls.radar_slots(RADAR_MAX_LOOKBACK, newest)
        while slots and len(frames) < frame_count:
            window, slots = slots[:RADAR_PROBE_WINDOW], slots[RADAR_PROBE_WINDOW:]
            with ThreadPoolExecutor(max_workers=len(window)) as pool:
                exists = list(pool.map(cls.radar_slot_exists, window))

            wanted = [at for at, ok in zip(window, exists) if ok is not False]
            wanted = wanted[: frame_count - len(frames)]
            if not wanted:
                continue

            workers = min(len(wanted), RADAR_DOWNLOAD_WORKERS)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                downloaded = pool.map(cls.download_radar_slot, wanted)
                frames.extend(frame for frame in downloaded if frame)

        frames.reverse()
        return frames

    @staticmethod
    def build_radar_gif(
        frames, width: int = RADAR_GIF_WIDTH, duration: int = RADAR_GIF_DURATION
    ) -> bytes:
        """把雷达图序列拼成一个循环播放的 GIF。"""
        from PIL import Image

        if not frames:
            raise RuntimeError("没有可用于生成动图的雷达图")

        images = []
        target = None
        for _, content in frames:
            with Image.open(io.BytesIO(content)) as image:
                frame = image.convert("RGB")
            if target is None:
                base_width, base_height = frame.size
                if width and base_width > width:
                    target = (width, max(1, round(base_height * width / base_width)))
                else:
                    target = frame.size
            if frame.size != target:
                frame = frame.resize(target, Image.LANCZOS)
            images.append(frame)

        # 所有帧共用同一套调色板，避免播放时整体颜色忽明忽暗
        palette_source = max(
            images, key=lambda image: len(image.getcolors(1 << 20) or [])
        )
        palette = palette_source.quantize(colors=256, method=Image.MEDIANCUT)
        quantized = [
            image.quantize(palette=palette, dither=Image.NONE) for image in images
        ]

        buffer = io.BytesIO()
        quantized[0].save(
            buffer,
            format="GIF",
            save_all=True,
            append_images=quantized[1:],
            duration=duration,
            loop=0,
            disposal=2,
            optimize=True,
        )
        return buffer.getvalue()

    async def initialize(self):
        """插件初始化方法"""

    @filter.command("help")
    async def xmhelp(self, event: AstrMessageEvent):
        help_msg = (
            "-----小明工具插件说明-----\n"
            "[xmhelp] 用于呼出这份说明\n"
            "[xmjrrp] 用于查看今日人品\n"
            "[xmdice 3d6 2d10] 掷骰，支持空格、+、中英文逗号和换行分隔多个骰式\n"
            "[xmtp] 台风信息\n"
            "[xmrd] 华东雷达回波动图（近一小时 GIF）\n"
        )
        logger.info(event.get_messages())
        yield event.plain_result(help_msg)

    @filter.command("jrrp")
    async def xmjrrp(self, event: AstrMessageEvent):
        qid = event.message_obj.sender.user_id

        rnd = random.Random()
        rnd.seed(int(date.today().strftime("%y%m%d")) + int(qid))
        lucknum = rnd.randint(1, 100)

        res = self.luck_simple(lucknum)[0]
        msg = f"您今日的幸运指数是 {lucknum}/100，{res}。"
        yield event.plain_result(msg)

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
        from astrbot.api.message_components import Image, Plain

        try:
            frames = await asyncio.to_thread(self.collect_radar_frames)
            if not frames:
                raise RuntimeError("未找到可用的华东雷达图")

            if len(frames) > 1:
                payload = await asyncio.to_thread(self.build_radar_gif, frames)
                # 图片过大时逐级缩小，避免适配器上传失败
                for width in (320, 260):
                    if len(payload) <= RADAR_GIF_MAX_BYTES:
                        break
                    payload = await asyncio.to_thread(
                        self.build_radar_gif, frames, width
                    )
            else:
                payload = frames[0][1]
        except Exception as exc:
            logger.exception("Failed to fetch radar images")
            yield event.plain_result(f"获取华东雷达图失败: {exc}")
            return

        start = frames[0][0].astimezone(RADAR_TIMEZONE)
        end = frames[-1][0].astimezone(RADAR_TIMEZONE)
        if len(frames) > 1:
            caption = (
                f"华东雷达回波动图，{len(frames)} 帧，"
                f"{start:%H:%M} ~ {end:%H:%M}（北京时间）"
            )
        else:
            caption = f"华东雷达回波，{start:%H:%M}（北京时间）"

        yield event.chain_result(
            [
                Plain("https://www.nmc.cn/publish/radar/huadong.html\n"),
                Plain(caption + "\n"),
                Image.fromBytes(payload),
            ]
        )

    async def terminate(self):
        """插件销毁方法"""
