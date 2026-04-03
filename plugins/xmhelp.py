# 在AstrBot中，你可以这样实现：
from astrbot.core import AstrBot
from astrbot.event import GroupMessageEvent

bot = AstrBot()

@bot.on_message(group=True)
async def handle_group_message(event: GroupMessageEvent):
    # 检查消息内容
    if "xmhelp" in event.message:
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
        await event.reply(help_msg)
