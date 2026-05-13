from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session

from app.models import AIResult, AITask


class AIService:
    """V1 only returns deterministic suggestions; real model calls stay behind this service."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def analyze_goods_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        required_fields = ("title", "price", "stock")
        for field in required_fields:
            if field not in payload or payload[field] in ("", None):
                issues.append({"field": field, "level": "error", "message": "缺少必填字段"})

        title = str(payload.get("title", ""))
        if len(title) < 8:
            issues.append({"field": "title", "level": "warning", "message": "标题偏短，建议补充核心卖点"})
        if payload.get("price") is not None and float(payload.get("price", 0)) <= 0:
            issues.append({"field": "price", "level": "error", "message": "价格必须大于 0"})

        result = {
            "summary": "商品 JSON 可发布" if not any(i["level"] == "error" for i in issues) else "商品 JSON 需要修正",
            "issues": issues,
            "confidence": 0.82,
            "can_execute": False,
        }
        self._record("goods_payload_check", payload, result)
        return result

    def explain_error(self, request_log: dict[str, Any], response_log: dict[str, Any]) -> dict[str, Any]:
        status_code = response_log.get("status_code")
        if status_code in (401, 403):
            reason = "登录态或权限可能失效"
            action = "建议检查 cookie 状态，并通过独立浏览器 Profile 重新登录"
        elif status_code == 429:
            reason = "平台可能触发限流"
            action = "建议降低并发、延长重试间隔，并记录触发接口"
        elif status_code and status_code >= 500:
            reason = "平台服务端或网络链路异常"
            action = "建议保留请求日志后重试"
        else:
            reason = "需要结合响应体继续判断"
            action = "建议查看 request_log 中的脱敏请求和响应"

        result = {
            "summary": reason,
            "recommended_action": action,
            "confidence": 0.7,
            "can_execute": False,
        }
        self._record("error_explain", {"request_log": request_log, "response_log": response_log}, result)
        return result

    def suggest_cleanup(self, goods_stats: list[dict[str, Any]]) -> dict[str, Any]:
        candidates = [
            item
            for item in goods_stats
            if int(item.get("days_without_order", 0)) >= 30 and int(item.get("stock", 0)) > 0
        ]
        result = {
            "summary": f"发现 {len(candidates)} 个可复核的清理候选商品",
            "candidates": candidates,
            "confidence": 0.76,
            "can_execute": False,
        }
        self._record("cleanup_suggest", {"goods_stats": goods_stats}, result)
        return result

    def _record(self, scene: str, input_json: dict[str, Any], result_json: dict[str, Any]) -> None:
        task = AITask(
            scene=scene,
            input_json=input_json,
            status="success",
            model_name="local-rule-v1",
            prompt_version="builtin-v1",
            finished_at=datetime.now(),
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        self.session.add(
            AIResult(
                ai_task_id=task.id or 0,
                result_json=result_json,
                summary=result_json.get("summary"),
                confidence=result_json.get("confidence"),
            )
        )
        self.session.commit()
