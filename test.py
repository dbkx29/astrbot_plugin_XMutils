import random


num = 2
dice = 6

send_msg=""
arr = []
for i in range(num):
    arr.append(random.randint(1, dice))

arr.sort()
send_msg+=f"({sum(arr)})"
for i in range(num):
    send_msg+=f"{arr[i]}+"
send_msg=send_msg[:-1] #删除尾部加号

# from astrbot.api.message_components import Node, Plain
# node = Node(
#     uin=2485981440,
#     name="🎲骰娘🎲",
#     content=[
#         Plain(send_msg),
#     ]
# )

print(send_msg)
