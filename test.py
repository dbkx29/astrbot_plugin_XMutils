from datetime import date, datetime, timedelta
import random
import re

import requests



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