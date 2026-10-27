"""采集域路由与载荷：capture 命令、状态载荷（阶段1.4 拆分）。

从 server.py 机械搬移；LocalServer 保留鉴权、生命周期、静态页与 WS
推送，本模块以 mixin 形式提供采集域 handler（self._context /
self._json_body / _environment_payload 等由宿主 LocalServer 提供）。
"""

from __future__ import annotations

from aiohttp import web

from spritelens.view_models.capture_diagnostics import capture_diagnostics
from spritelens.capture.base import SourceError
from spritelens.view_models.capture_vm import CaptureSnapshot, EnvironmentBusyError
from spritelens.web.payloads import pet_summary_payload
from spritelens.web.account_state import account_domains_payload
from spritelens.view_models.pet_vm import PetFilters, PetView
from spritelens.services.capture_service import RecordingCommandError


class CaptureRoutesMixin:
    """采集域 API：/api/capture*、/api/state 及 capture/state 载荷。"""

    async def _api_capture(self, request: web.Request) -> web.Response:
        return web.json_response(self._capture_payload())

    async def _api_capture_environment(self, request: web.Request) -> web.Response:
        try:
            await self._run_blocking(self._context.capture_vm.refresh_environment)
        except EnvironmentBusyError as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except Exception as exc:
            return web.json_response({"error": f"环境重新检测失败：{exc}"}, status=500)
        return web.json_response(self._capture_payload())

    async def _api_capture_ifaces(self, request: web.Request) -> web.Response:
        try:
            ifaces = await self._run_blocking(self._context.capture_vm.refresh_ifaces)
        except SourceError as exc:
            return web.json_response({"error": f"网卡枚举失败：{exc}"}, status=500)
        # 活跃网卡排前面（PowerShell 查询在开销时执行；失败则保持原序）
        from spritelens.capture.nic_rank import rank_ifaces

        ifaces = await self._run_blocking(rank_ifaces, list(ifaces))
        return web.json_response(
            {"ifaces": [{"name": name, "description": desc} for name, desc in ifaces]}
        )

    async def _api_capture_iface(self, request: web.Request) -> web.Response:
        try:
            body = await self._json_body(request)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        name = body.get("name")
        # 显式字符串契约（D08）：缺字段/null 不再默认成空串清空网卡；
        # 清空选择仍被支持，但必须提交明确的空字符串
        if not isinstance(name, str):
            return web.json_response(
                {"error": "字段 name 必须是字符串（清空选择用空字符串）"}, status=400
            )
        try:
            await self._run_blocking(self._context.capture_vm.select_iface, name)
        except OSError as exc:
            return web.json_response(
                {"error": f"下次采集使用的网卡选择保存失败（重启后可能恢复原值）：{exc}"}, status=500
            )
        return web.json_response(self._capture_payload())

    async def _api_capture_start(self, request: web.Request) -> web.Response:
        await self._run_blocking(self._context.capture_vm.start)
        return web.json_response(self._capture_payload())

    async def _api_capture_stop(self, request: web.Request) -> web.Response:
        try:
            await self._run_blocking(self._context.capture_vm.stop)
        except TimeoutError as exc:
            return web.json_response({"error": str(exc), "stopped": False}, status=503)
        return web.json_response(self._capture_payload())

    async def _api_capture_recording(self, request: web.Request) -> web.Response:
        try:
            body = await self._json_body(request)
            enabled = self._require_bool(body, "enabled")
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        try:
            await self._run_blocking(self._context.capture_vm.set_recording_requested, enabled)
        except RecordingCommandError as exc:
            message = {
                "start": "录制器启动失败，未开始录制",
                "stop": "录制器停止失败，请确认当前录制状态后重试",
                "save": "录制意愿已生效，但偏好保存失败（重启后可能恢复原值）",
            }[exc.phase]
            return web.json_response(
                {"error": f"{message}：{exc}", "error_kind": exc.phase,
                 "requested": exc.requested, "recording": exc.recording, "saved": False},
                status=500,
            )
        return web.json_response(self._capture_payload())

    async def _api_capture_autostart(self, request: web.Request) -> web.Response:
        try:
            body = await self._json_body(request)
            enabled = self._require_bool(body, "enabled")
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        try:
            await self._run_blocking(self._context.capture_vm.set_autostart, enabled)
        except OSError as exc:
            return web.json_response(
                {"error": f"自动采集设置已生效，但保存失败（重启后可能恢复原值）：{exc}"}, status=500
            )
        return web.json_response(self._capture_payload())

    async def _api_capture_automation(self, request: web.Request) -> web.Response:
        try:
            body = await self._json_body(request)
            enabled = self._require_bool(body, "enabled")
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        try:
            await self._run_blocking(
                self._context.game_automation.configure,
                enabled=enabled,
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except OSError as exc:
            return web.json_response({"error": f"自动监听任务保存失败：{exc}"}, status=500)
        return web.json_response(self._capture_payload())

    async def _api_capture_key(self, request: web.Request) -> web.Response:
        try:
            body = await self._json_body(request)
        except ValueError as exc:
            return web.json_response({"error": str(exc), "ok": False}, status=400)
        text = body.get("text")
        if not isinstance(text, str):
            return web.json_response({"error": "字段 text 必须是字符串", "ok": False}, status=400)
        ok, message = await self._run_blocking(self._context.capture_vm.apply_manual_key, text)
        return web.json_response({"ok": ok, "message": message}, status=200 if ok else 400)

    async def _api_npcap_install(self, request: web.Request) -> web.Response:
        await self._run_blocking(self._context.capture_vm.start_npcap_install)
        return web.json_response(self._capture_payload())

    async def _api_rsc(self, request: web.Request) -> web.Response:
        await self._run_blocking(self._context.capture_vm.start_disable_rsc)
        return web.json_response(self._capture_payload())

    async def _api_state(self, request: web.Request) -> web.Response:
        return web.json_response(self._state_payload())

    # -- 状态载荷 ------------------------------------------------------
    def _capture_payload(self, snapshot: CaptureSnapshot | None = None) -> dict:
        ctx = self._context
        vm = ctx.capture_vm
        if snapshot is None:
            snapshot = vm.snapshot()
        install = vm.install_state()
        return {
            "decrypt_ok": snapshot.totals.decrypt_ok,
            "raw_chunks": snapshot.totals.raw_chunks,
            "port": vm.port,
            "diagnostics": capture_diagnostics(snapshot, vm.environment_report(), port=vm.port,
                extra_ports=vm.extra_ports, environment_error=vm.environment_error,
                environment_checking=vm.environment_checking),
            "running": snapshot.running,
            "iface": snapshot.iface,
            "extra_ports": list(vm.extra_ports),
            "recording": snapshot.recording,
            "recording_requested": vm.recording_requested,
            "autostart": vm.autostart,
            "automation": ctx.game_automation.snapshot() if ctx.game_automation is not None else {
                "enabled": False, "process_name": "", "task_name": "",
                "audit_guidance": "",
            },
            "recorded_chunks": snapshot.recorded_chunks,
            "flow_count": snapshot.flow_count,
            "any_key": snapshot.any_key,
            "last_error": snapshot.last_error,
            "event_log_name": snapshot.event_log_name,
            # 静默丢数据信号：队列过载与重组超限（>0 时采集页提示）
            "dropped_chunks": snapshot.dropped_chunks,
            "dropped_segments": snapshot.dropped_segments,
            "event_log_dropped": snapshot.event_log_dropped,
            "event_log_error": snapshot.event_log_error,
            "totals": {
                "decrypt_ok": snapshot.totals.decrypt_ok,
                "decrypt_fail": snapshot.totals.decrypt_fail,
                "key_miss": snapshot.totals.key_miss,
                "parse_fail": snapshot.totals.parse_fail,
                "raw_chunks": snapshot.totals.raw_chunks,
                "raw_bytes": snapshot.totals.raw_bytes,
            },
            "sessions": [
                {"session_id": s.session_id, "has_key": s.has_key, "data_frames": s.data_frames,
                 "decrypt_ok": s.decrypt_ok, "failures": s.failures, "uid": str(s.uid), "name": s.name,
                 "last_activity": s.last_activity, "status": s.status if snapshot.running else "stopped"}
                for s in snapshot.sessions
            ],
            "environment": self._environment_payload(),
            "install": {
                "phase": install.phase,
                "message": install.message,
                "progress": install.progress,
            },
        }

    def _state_payload(self, view: PetView | None = None) -> dict:
        ctx = self._context
        if view is None:
            pets = self._pet_summary()
        else:
            # bootstrap 与 /api/pets 共用同一快照：必须用传入的 view，不复用缓存
            pets = pet_summary_payload(view, ctx.static_data)
        capture = ctx.capture_vm.snapshot()
        install = ctx.capture_vm.install_state()
        nearby = ctx.scene_repository.snapshot() if ctx.scene_repository is not None else None
        return {
            **account_domains_payload(pets["uid"], ctx.egg_box, ctx.home_repo),
            "uid": pets["uid"],
            "pets_version": pets["version"],
            "pets_total": pets["stats"]["total"],
            "identity": pets["identity"],
            "cached_identity": pets["cached_identity"],
            "stats": pets["stats"],
            "account_epoch": self._account_epoch,
            "nearby": {"uid": str(nearby.uid), "version": nearby.version, "observation_id": nearby.observation_id, "phase": nearby.phase, "coverage_error": nearby.coverage_error} if nearby is not None else None,
            "capture": self._capture_payload(capture),
            # 环境探测在启动路径上异步进行（RSC 检查约 1.8s）；
            # 探测完成后 report 变化 → 此载荷变化 → WS 推送 → 横幅自动刷新
            "environment": self._environment_payload(),
            # Npcap 安装器在后台下载/提权；状态也要进入 WS，页面才能自动显示
            # 下载进度、安装向导已打开或失败，而不是停留在点击瞬间的状态。
            "install": {
                "phase": install.phase,
                "message": install.message,
                "progress": install.progress,
            },
        }

    def _pet_summary(self) -> dict:
        """宠物摘要按（归属 uid、仓库版本、身份、账号代次）复用（PERF07）。

        状态推送每 0.5s 取一次；静止采集时宠物仓库的输入不变，而重新排序
        快照并聚合统计是每拍的主要构造成本，因此按依赖项缓存摘要。
        采集计数、安装进度、环境与附近数据仍在每次调用时重新读取。
        """
        ctx = self._context
        repo = ctx.pet_repository
        key = (
            repo.display_uid,
            repo.version,
            repo.identity,
            repo.cached_identity,
            self._account_epoch,
        )
        cache = self._pet_summary_cache
        if cache is not None and cache[0] == key:
            return cache[1]
        summary = pet_summary_payload(ctx.pet_vm.view_with(PetFilters()), ctx.static_data)
        self._pet_summary_cache = (key, summary)
        return summary

    def _environment_payload(self) -> dict:
        """环境报告 → JSON（/api/capture 与 WS state 推送共用一份契约）。"""
        report = self._context.capture_vm.environment_report()
        return {
            "checking": self._context.capture_vm.environment_checking,
            "refresh_error": self._context.capture_vm.environment_error,
            "installed": report.installed,
            "message": report.message,
            "rsc_enabled": report.rsc_enabled,
            "rsc_adapter": report.rsc_adapter,
        }


__all__ = ["CaptureRoutesMixin"]
