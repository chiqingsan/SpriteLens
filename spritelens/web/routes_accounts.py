"""本地历史账号列表与切换路由。"""

from __future__ import annotations

import sqlite3

from aiohttp import web

from spritelens.services.account_selection_service import AccountNotFound, AccountSwitchBusy


class AccountRoutesMixin:
    """账号管理 API；业务读取与跨域应用由 AccountSelectionService 负责。"""

    async def _api_accounts(self, request: web.Request) -> web.Response:
        service = self._context.account_selection
        if service is None:
            return web.json_response({"error": "账号管理服务不可用"}, status=503)
        try:
            return await self._thread_json_response(service.accounts_payload)
        except sqlite3.Error:
            return web.json_response({"error": "本地数据读取失败，请检查数据库"}, status=500)

    async def _api_accounts_select(self, request: web.Request) -> web.Response:
        service = self._context.account_selection
        if service is None:
            return web.json_response({"error": "账号管理服务不可用"}, status=503)
        try:
            body = await self._json_body(request)
            uid = body.get("uid")
            if type(uid) is not int or uid <= 0:
                raise ValueError("字段 uid 必须是正整数")
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        try:
            await self._run_blocking(service.select, uid)
            self._account_epoch += 1
            def build_payload() -> dict:
                accounts = service.accounts_payload()
                return {
                    "account": next(item for item in accounts["accounts"] if item["uid"] == uid),
                    "accounts": accounts,
                    "state": self._state_payload(),
                }
            return await self._thread_json_response(build_payload)
        except AccountSwitchBusy as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except AccountNotFound as exc:
            return web.json_response({"error": str(exc)}, status=404)
        except (sqlite3.Error, OSError, RuntimeError):
            return web.json_response({"error": "本地数据读取失败，请检查数据库"}, status=500)


__all__ = ["AccountRoutesMixin"]
