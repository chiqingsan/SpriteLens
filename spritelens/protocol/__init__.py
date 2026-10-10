"""协议层：模式无关的纯函数集（切帧/解密/拆分/wire 解码/schema 双路解码）。

本包只依赖标准库与 pycryptodome，不做任何 IO 与线程操作，
保证可离线单测与被任意接入层复用。
"""

from spritelens.protocol.crypto import decrypt_data_body, encrypt_data_body, extract_ack_key
from spritelens.protocol.frames import CMD_ACK, CMD_DATA, GcpFrame, FrameStream, parse_frames
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.protocol.records import Direction, Record, split_record
from spritelens.protocol.schema import SchemaLibrary, get_library, load_library
from spritelens.protocol.wire import WireField, decode_wire

__all__ = [
    "CMD_ACK",
    "CMD_DATA",
    "Direction",
    "FrameStream",
    "GcpFrame",
    "OpcodeCatalog",
    "Record",
    "SchemaLibrary",
    "WireField",
    "decrypt_data_body",
    "decode_wire",
    "encrypt_data_body",
    "extract_ack_key",
    "get_library",
    "load_library",
    "parse_frames",
    "split_record",
]
