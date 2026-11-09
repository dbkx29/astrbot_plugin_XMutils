from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import asyncio
import io
import os
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
RADAR_FRAME_COUNT = 10  # 默认拼进 GIF 的帧数，10 帧约 1 小时
RADAR_MAX_FRAME_COUNT = 16  # 允许用户指定的最大帧数
RADAR_NEWEST_LOOKBACK = 4  # 查找最新一帧时向前探测的时次数
RADAR_MAX_LOOKBACK = 48  # 收集帧时最多向前探测的时次数
RADAR_PROBE_WINDOW = 12  # 每轮处理的时次数
RADAR_GIF_WIDTH = 0  # GIF 宽度，0 表示保持原始分辨率
RADAR_GIF_DURATION = 200  # 每帧播放时长（毫秒）
RADAR_GIF_MAX_BYTES = 4_000_000  # 超过该体积时缩小
RADAR_DOWNLOAD_WORKERS = 12  # 并发下载雷达图的线程数
RADAR_CACHE_TTL_HOURS = 6  # 雷达图本地缓存的保留时长
RADAR_WARMUP_ENABLED = True  # 后台预热缓存，让 /xmrd 不用现下载
RADAR_WARMUP_INTERVAL = 300  # 秒，后台检查新时次的间隔
RADAR_REQUEST_TIMEOUT = 15.05
RADAR_PROBE_TIMEOUT = 8  # 探测（HEAD）超时，避免慢连接长时间卡住
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

    @classmethod
    def radar_cache_dir(cls) -> str:
        """雷达图缓存目录，历史时次的图片不会变，缓存下来可以省掉重复下载。"""
        cached = getattr(cls, "_radar_cache_dir", None)
        if cached is not None:
            return cached

        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

            base = get_astrbot_plugin_data_path()
        except Exception:
            base = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")

        path = os.path.join(str(base), "xmutils", "radar")
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            logger.warning(f"无法创建雷达图缓存目录，将不做本地缓存: {path}")
            path = ""
        cls._radar_cache_dir = path
        return path

    @classmethod
    def radar_cache_path(cls, at: datetime):
        directory = cls.radar_cache_dir()
        if not directory:
            return None
        return os.path.join(directory, f"radar_{at:%Y%m%d%H%M}.png")

    @classmethod
    def read_cached_radar(cls, at: datetime):
        path = cls.radar_cache_path(at)
        if not path:
            return None
        try:
            with open(path, "rb") as file:
                content = file.read()
        except OSError:
            return None
        if len(content) < 5000 or not content.startswith(b"\x89PNG"):
            return None
        return content

    @classmethod
    def write_cached_radar(cls, at: datetime, content: bytes):
        path = cls.radar_cache_path(at)
        if not path:
            return
        temp = f"{path}.{os.getpid()}.part"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(temp, "wb") as file:
                file.write(content)
            os.replace(temp, path)
        except OSError:
            logger.warning(f"写入雷达图缓存失败: {path}")

    @classmethod
    def prune_radar_cache(cls, ttl_hours: int = RADAR_CACHE_TTL_HOURS):
        directory = cls.radar_cache_dir()
        if not directory:
            return
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).timestamp()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        for entry in entries:
            try:
                if entry.is_file() and entry.stat().st_mtime < cutoff:
                    os.remove(entry.path)
            except OSError:
                continue

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
                cls.radar_url(at), headers=RADAR_HEADERS, timeout=RADAR_PROBE_TIMEOUT
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
        """下载某个时次的雷达图并写入缓存，失败时返回 None。"""
        try:
            response = requests.get(
                cls.radar_url(at), headers=RADAR_HEADERS, timeout=RADAR_REQUEST_TIMEOUT
            )
        except requests.RequestException:
            return None

        if response.status_code != 200 or len(response.content) < 5000:
            return None
        cls.write_cached_radar(at, response.content)
        return at, response.content

    @classmethod
    def find_newest_radar_slot(cls):
        """并发探测最近几个时次，返回最新一张可用的雷达图时次。"""
        slots = cls.radar_slots(RADAR_NEWEST_LOOKBACK)
        with ThreadPoolExecutor(max_workers=len(slots)) as pool:
            states = list(pool.map(cls.radar_slot_exists, slots))

        for at, state in zip(slots, states):
            if state is True:
                return at
        for at, state in zip(slots, states):
            if state is None:  # 探测失败时先按它取，反正后续下载还会再筛一次
                return at
        return None

    @classmethod
    def collect_radar_frames(cls, frame_count: int = RADAR_FRAME_COUNT):
        """从最近的时次往前收集 frame_count 张雷达图，按时间正序返回 (时间, 图片字节)。"""
        newest = cls.find_newest_radar_slot()
        if newest is None:
            raise RuntimeError("最近几个小时没有可用的华东雷达图")

        frames = []
        slots = cls.radar_slots(RADAR_MAX_LOOKBACK, newest)
        for start in range(0, len(slots), RADAR_PROBE_WINDOW):
            if len(frames) >= frame_count:
                break
            # 只从最新的一端取还需要的时次，保证 GIF 一定包含最新一张图
            need = min(RADAR_PROBE_WINDOW, frame_count - len(frames))
            candidates = slots[start : start + need]

            loaded = {}
            unknown = []
            for at in candidates:
                content = cls.read_cached_radar(at)
                if content:
                    loaded[at] = content
                else:
                    unknown.append(at)

            if unknown:
                with ThreadPoolExecutor(max_workers=len(unknown)) as pool:
                    states = list(pool.map(cls.radar_slot_exists, unknown))
                missing = [
                    at
                    for at, state in zip(unknown, states)
                    if state is not False and at not in loaded
                ]
                if missing:
                    workers = min(len(missing), RADAR_DOWNLOAD_WORKERS)
                    with ThreadPoolExecutor(max_workers=workers) as pool:
                        for frame in pool.map(cls.download_radar_slot, missing):
                            if frame:
                                loaded[frame[0]] = frame[1]

            frames.extend((at, loaded[at]) for at in candidates if at in loaded)

        cls.prune_radar_cache()
        frames = frames[:frame_count]
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
        if not RADAR_WARMUP_ENABLED:
            return
        task = getattr(self, "_radar_warmer_task", None)
        if task is not None and not task.done():
            return
        self._radar_warmer_task = asyncio.create_task(self._warm_radar_cache())

    async def _warm_radar_cache(self):
        """后台把最近一段时间的雷达图缓存好，用户调用时只需要拼 GIF。"""
        while True:
            try:
                await asyncio.to_thread(self.collect_radar_frames, RADAR_FRAME_COUNT)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"雷达图缓存预热失败，稍后重试: {exc}")
            await asyncio.sleep(RADAR_WARMUP_INTERVAL)

    @filter.command("help")
    async def xmhelp(self, event: AstrMessageEvent):
        help_msg = (
            "-----小明工具插件说明-----\n"
            "[xmhelp] 用于呼出这份说明\n"
            "[xmjrrp] 用于查看今日人品\n"
            "[xmdice 3d6 2d10] 掷骰，支持空格、+、中英文逗号和换行分隔多个骰式\n"
            "[xmtp] 台风信息\n"
            "[xmrd 10] 华东雷达回波动图（默认 10 帧≈1 小时，可写 2~16）\n"
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
    async def xmrd(self, event: AstrMessageEvent, frames: int = RADAR_FRAME_COUNT):
        from astrbot.api.message_components import Image, Plain

        try:
            frame_count = max(2, min(int(frames), RADAR_MAX_FRAME_COUNT))
            frames_data = await asyncio.to_thread(
                self.collect_radar_frames, frame_count
            )
            if not frames_data:
                raise RuntimeError("未找到可用的华东雷达图")

            if len(frames_data) > 1:
                payload = await asyncio.to_thread(self.build_radar_gif, frames_data)
                # 体积过大时抽帧重建，保持原始分辨率不牺牲清晰度
                while len(payload) > RADAR_GIF_MAX_BYTES and len(frames_data) > 4:
                    frames_data = frames_data[::2]
                    payload = await asyncio.to_thread(
                        self.build_radar_gif, frames_data
                    )
            else:
                payload = frames_data[0][1]
        except Exception as exc:
            logger.exception("Failed to fetch radar images")
            yield event.plain_result(f"获取华东雷达图失败: {exc}")
            return

        start = frames_data[0][0].astimezone(RADAR_TIMEZONE)
        end = frames_data[-1][0].astimezone(RADAR_TIMEZONE)
        if len(frames_data) > 1:
            caption = (
                f"华东雷达回波动图，{len(frames_data)} 帧，"
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
        task = getattr(self, "_radar_warmer_task", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
