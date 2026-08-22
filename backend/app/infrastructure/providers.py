from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.errors import DependencyUnavailable


class DemoProviderDisabled(DependencyUnavailable):
    def __init__(self) -> None:
        super().__init__("demo_provider")


class _DemoProvider:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise DemoProviderDisabled()


class DemoSmsProvider(_DemoProvider):
    def __init__(self, enabled: bool, code: str) -> None:
        super().__init__(enabled)
        self._code = code

    async def send_code(self, destination: str, purpose: str) -> dict[str, object]:
        self._require_enabled()
        return {
            "delivery": "LOCAL_DEMO",
            "masked_destination": destination[:2] + "***" + destination[-2:],
            "purpose": purpose,
            "demo_code": self._code,
            "notice": "本地模拟短信，未发送至真实号码。",
        }


class DemoPaymentProvider(_DemoProvider):
    async def pay(self, outcome: str) -> dict[str, object]:
        self._require_enabled()
        return {
            "outcome": outcome,
            "provider_reference": f"DEMO-PAY-{uuid4().hex[:12].upper()}",
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "notice": "本地模拟缴费，未发生真实资金交易。",
        }


class DemoFaceVerificationProvider(_DemoProvider):
    async def verify(self, outcome: str) -> dict[str, object]:
        self._require_enabled()
        return {
            "outcome": outcome,
            "biometric_data_stored": False,
            "notice": "本地模拟身份核验，不采集或保存真实生物信息。",
        }


class DemoDeliveryProvider(_DemoProvider):
    async def create(self) -> dict[str, object]:
        self._require_enabled()
        return {
            "provider_reference": f"DEMO-MAIL-{uuid4().hex[:12].upper()}",
            "notice": "本地模拟邮寄，未创建真实快递订单。",
        }
