"""SpriteLens（小洛探探）：《洛克王国：世界》数据观测工具。

应用层与协议层解绑：capture 接入层可插拔（首版 Npcap 旁听，预留 MITM 代理位），
protocol 协议层为模式无关纯函数，功能层只消费统一的 PacketEvent。
"""

__version__ = "1.0.0"

APP_NAME = "SpriteLens"
APP_DISPLAY_NAME = "小洛探探"
