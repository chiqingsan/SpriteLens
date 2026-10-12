"""schema 双路解码与 opcode 目录测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.protocol.schema import SchemaLibrary, load_library
from tests._synth import make_protobuf_payload, make_varint


def _make_library(tmp: Path) -> SchemaLibrary:
    messages_dir = tmp / "messages"
    messages_dir.mkdir()
    (messages_dir / "PetAttributeData.json").write_text(
        json.dumps(
            {
                "messages": {
                    "PetAttributeData": {
                        "fields": {
                            "1": {"name": "total_race", "type": "uint32"},
                            "2": {"name": "talent", "type": "uint32"},
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return load_library(tmp)


class SchemaLibraryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.lib = _make_library(Path(self._tmp.name))

    def test_decode_with_schema_names(self):
        payload = make_varint((1 << 3) | 0) + make_varint(850)
        out = self.lib.decode(payload, "PetAttributeData")
        self.assertEqual(out[0]["name"], "total_race")
        self.assertEqual(out[0]["value"], "850")

    def test_decode_unknown_message_falls_back_to_field_n(self):
        payload = make_protobuf_payload()
        out = self.lib.decode(payload, "NobodyKnows")
        self.assertEqual(out[0]["name"], "field_1")

    def test_decode_without_message_name(self):
        out = self.lib.decode(make_protobuf_payload(), None)
        self.assertEqual(len(out), 3)

    def test_nested_child_schema_lookup(self):
        parent_dir = Path(self._tmp.name)
        (parent_dir / "messages" / "Parent.json").write_text(
            json.dumps(
                {
                    "messages": {
                        "Parent": {
                            "fields": {
                                "3": {"name": "inner", "type": "PetAttributeData"}
                            }
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        lib = load_library(parent_dir)
        nested = make_varint((1 << 3) | 0) + make_varint(850)
        payload = make_varint((3 << 3) | 2) + make_varint(len(nested)) + nested
        out = lib.decode(payload, "Parent")
        self.assertEqual(out[0]["name"], "inner")
        self.assertEqual(out[0]["children"][0]["name"], "total_race")

    def test_empty_dir_degrades(self):
        empty = Path(self._tmp.name) / "empty"
        empty.mkdir()
        lib = load_library(empty)
        self.assertEqual(lib.messages, {})
        self.assertEqual(lib.decode(make_protobuf_payload(), None)[0]["name"], "field_1")

    def test_get_library_default_empty(self):
        from spritelens.protocol import schema as schema_mod

        saved = schema_mod._library
        schema_mod._library = None
        try:
            lib = schema_mod.get_library()
            self.assertEqual(lib.messages, {})
        finally:
            schema_mod._library = saved


class SchemaLibraryDirectTest(unittest.TestCase):
    def test_field_defs_namespace_fallback(self):
        lib = SchemaLibrary(messages={"PetAttributeData": {1: {"name": "x", "type": ""}}}, source_dir=None)
        self.assertEqual(lib.field_defs("Next.PetAttributeData"), {1: {"name": "x", "type": ""}})

    def test_instance_decode_uses_injected_library_not_global(self):
        """注入实例递归解码子消息只用当前实例的定义（R07）。

        旧实现 _field_to_dict 从 get_library() 取子定义：实例库与全局库
        不一致时（多测试库并存、未来按游戏版本选库）子消息命名被全局库
        覆盖或退化为 field_N，且依赖全局加载顺序。
        """
        from spritelens.protocol import schema as schema_mod

        nested = make_varint((1 << 3) | 0) + make_varint(850)
        # Root→Child：相同字段号 1 在两个实例库中命名不同
        lib_a = SchemaLibrary(
            messages={
                "Root": {1: {"name": "child_a", "type": "Child"}},
                "Child": {1: {"name": "value_a", "type": ""}},
            },
            source_dir=None,
        )
        lib_b = SchemaLibrary(
            messages={
                "Root": {1: {"name": "child_b", "type": "Child"}},
                "Child": {1: {"name": "value_b", "type": ""}},
            },
            source_dir=None,
        )
        # 全局库为空：递归若读全局库将退化为 field_1
        saved = schema_mod._library
        schema_mod._library = None
        try:
            payload = make_varint((1 << 3) | 2) + make_varint(len(nested)) + nested
            out_a = lib_a.decode(payload, "Root")
            out_b = lib_b.decode(payload, "Root")
        finally:
            schema_mod._library = saved
        self.assertEqual(out_a[0]["name"], "child_a")
        self.assertEqual(out_a[0]["children"][0]["name"], "value_a")
        self.assertEqual(out_b[0]["name"], "child_b")
        self.assertEqual(out_b[0]["children"][0]["name"], "value_b")


class OpcodeCatalogTest(unittest.TestCase):
    def _write(self, tmp: Path, data: dict) -> Path:
        path = tmp / "opcodes.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def test_load_and_display(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                Path(tmp),
                {"opcodes": {"0x1316": {"name": "BattleEnterNotify", "category": "battle", "message": None}}},
            )
            catalog = OpcodeCatalog.load(path)
        self.assertEqual(catalog.display_name(0x1316), "BattleEnterNotify")
        self.assertEqual(catalog.lookup(0x1316).category, "battle")
        self.assertEqual(catalog.display_name(0x9999), "op_0x9999")

    def test_missing_file_degrades(self):
        catalog = OpcodeCatalog.load(Path("Z:/definitely/not/exists/opcodes.json"))
        self.assertEqual(catalog.size, 0)
        self.assertEqual(catalog.display_name(0x0001), "op_0x0001")

    def test_invalid_entries_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), {"opcodes": {"not-hex": {"name": "x"}, "0x1": {"name": "ok"}}})
            catalog = OpcodeCatalog.load(path)
        self.assertEqual(catalog.size, 1)


if __name__ == "__main__":
    unittest.main()
