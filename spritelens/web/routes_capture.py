"""采集域路由与载荷：capture 命令、状态载荷（阶段1.4 拆分）。

从 server.py 机械搬移；LocalServer 保留鉴权、生命周期、静态页与 WS
推送，本模块以 mixin 形式提供采集域 handler（self._context /
self._json_body / _environment_payload 等由宿主 LocalServer 提供）。
"""

from __future__ import annotations

import asyncio

from aiohttp import web

from spritelens.web.payloads import type_color_for
from spritelens.web.server_helpers import _as_bool, _as_int


class CaptureRoutesMixin:
    """采集域 API：/api/capture*、/api/state 及 capture/state 载荷。"""

    async def _api_capture(self, request: web.Request) -> web.Response:
        return web.json_response(self._capture_payload())

    async def _api_capture_ifaces(self, request: web.Request) -> web.Response:
        ifaces = await asyncio.to_thread(self._context.capture_vm.refresh_ifaces)
        # 活跃网卡排前面（PowerShell 查询在开销时执行；失败则保持原序）
        from spritelens.capture.nic_rank import rank_ifaces

        ifaces = await asyncio.to_thread(rank_ifaces, list(ifaces))
        return web.json_response(
            {"ifaces": [{"name": name, "description": desc} for name, desc in ifaces]}
        )

    async def _api_capture_iface(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        await asyncio.to_thread(self._context.capture_vm.select_iface, str(body.get("name") or ""))
        return web.json_response(self._capture_payload())

    async def _api_capture_start(self, request: web.Request) -> web.Response:
        await asyncio.to_thread(self._context.capture_vm.start)
        return web.json_response(self._capture_payload())

    async def _api_capture_stop(self, request: web.Request) -> web.Response:
        await asyncio.to_thread(self._context.capture_vm.stop)
        return web.json_response(self._capture_payload())

    async def _api_capture_recording(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        await asyncio.to_thread(
            self._context.capture_vm.set_recording_requested, bool(body.get("enabled"))
        )
        return web.json_response(self._capture_payload())

    async def _api_capture_autostart(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        await asyncio.to_thread(
            self._context.capture_vm.set_autostart, bool(body.get("enabled"))
        )
        return web.json_response(self._capture_payload())

    async def _api_capture_key(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        ok, message = await asyncio.to_thread(
            self._context.capture_vm.apply_manual_key, str(body.get("text") or "")
        )
        return web.json_response({"ok": ok, "message": message}, status=200 if ok else 400)

    async def _api_npcap_install(self, request: web.Request) -> web.Response:
        await asyncio.to_thread(self._context.capture_vm.start_npcap_install)
        return web.json_response(self._capture_payload())

    async def _api_rsc(self, request: web.Request) -> web.Response:
        await asyncio.to_thread(self._context.capture_vm.start_disable_rsc)
        return web.json_response(self._capture_payload())

    async def _api_state(self, request: web.Request) -> web.Response:
        return web.json_response(self._state_payload())

    # -- 状态载荷 ------------------------------------------------------
    def _capture_payload(self) -> dict:
        ctx = self._context
        vm = ctx.capture_vm
        snapshot = vm.snapshot()
        install = vm.install_state()
        return {
            "running": snapshot.running,
            "iface": snapshot.iface,
            "extra_ports": list(vm.extra_ports),
            "recording": snapshot.recording,
            "recording_requested": vm.recording_requested,
            "autostart": vm.autostart,
            "recorded_chunks": snapshot.recorded_chunks,
            "flow_count": snapshot.flow_count,
            "any_key": snapshot.any_key,
            "last_error": snapshot.last_error,
            "event_log_name": snapshot.event_log_name,
            # 静默丢数据信号：队列过载与重组超限（>0 时采集页提示）
            "dropped_chunks": snapshot.dropped_chunks,
            "dropped_segments": snapshot.dropped_segments,
            "event_log_dropped": snapshot.event_log_dropped,
            "totals": {
                "decrypt_ok": snapshot.totals.decrypt_ok,
                "decrypt_fail": snapshot.totals.decrypt_fail,
                "key_miss": snapshot.totals.key_miss,
                "parse_fail": snapshot.totals.parse_fail,
                "raw_chunks": snapshot.totals.raw_chunks,
                "raw_bytes": snapshot.totals.raw_bytes,
            },
            "sessions": [
                {"session_id": s.session_id, "has_key": s.has_key, "data_frames": s.data_frames}
                for s in snapshot.sessions
            ],
            "environment": self._environment_payload(),
            "install": {
                "phase": install.phase,
                "message": install.message,
                "progress": install.progress,
            },
        }

    def _state_payload(self) -> dict:
        ctx = self._context
        capture = ctx.capture_vm.snapshot()
        identity = ctx.pet_repository.identity
        cached = ctx.pet_repository.cached_identity
        stats = ctx.pet_vm.stats()
        return {
            "egg_box_version": ctx.egg_box.version() if ctx.egg_box is not None else 0,
            "egg_box_total": len(ctx.egg_box.snapshot()) if ctx.egg_box is not None else 0,
            "home_version": ctx.home_repo.version() if ctx.home_repo is not None else 0,
            "flower_version": ctx.flower_repo.version() if ctx.flower_repo is not None else 0,
            "pets_version": ctx.pet_vm.version(),
            "pets_total": stats.total,
            "events_total": ctx.events_vm.total_events,
            "identity": (
                {"uid": identity.uid, "name": identity.name, "level": identity.level}
                if identity is not None
                else None
            ),
            "cached_identity": {"uid": cached.uid, "name": cached.name, "level": cached.level} if cached else None,
            "stats": {
                "total": stats.total,
                "maxed": stats.maxed,
                "max_level": stats.max_level,
                "types": [
                    {"name": name, "count": count, "color": type_color_for(self._context.static_data, name)}
                    for name, count in stats.type_counts
                ],
            },
            "capture": {
                "running": capture.running,
                "recording": capture.recording,
                "recorded_chunks": capture.recorded_chunks,
                "flow_count": capture.flow_count,
                "any_key": capture.any_key,
                "last_error": capture.last_error,
                "decrypt_ok": capture.totals.decrypt_ok,
                "raw_chunks": capture.totals.raw_chunks,
            },
            # 环境探测在启动路径上异步进行（RSC 检查约 1.8s）；
            # 探测完成后 report 变化 → 此载荷变化 → WS 推送 → 横幅自动刷新
            "environment": self._environment_payload(),
        }

    def _environment_payload(self) -> dict:
        """环境报告 → JSON（/api/capture 与 WS state 推送共用一份契约）。"""
        report = self._context.capture_vm.environment_report()
        return {
            "installed": report.installed,
            "message": report.message,
            "rsc_enabled": report.rsc_enabled,
            "rsc_adapter": report.rsc_adapter,
        }


__all__ = ["CaptureRoutesMixin"]
