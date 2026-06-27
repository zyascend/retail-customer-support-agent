"""Screen pop — 模拟真实坐席进线：身份即设 + 主动查一次订单。

身份是渠道带入的（直接设置 ``authenticated_user_id``，无需 tool）；
订单是进线后主动调 ``list_user_orders`` 查一次的显式动作（非自动 pop）。
"""

from __future__ import annotations

from app.agent.models import SessionState
from app.tools.gateway import ToolGateway


class ScreenPop:
    def __init__(self, gateway: ToolGateway) -> None:
        self._gateway = gateway

    def apply(self, session: SessionState, customer_id: str) -> None:
        # 步骤1：身份进线即有（渠道带入，无需 tool）
        session.authenticated_user_id = customer_id
        session.auth_method = "screen_pop"

        # 步骤2：客户卡
        user_record = self._gateway.execute(
            state=session,
            tool_name="get_user_details",
            arguments={"user_id": customer_id},
        )
        if user_record.status == "success" and isinstance(
            user_record.observation, dict
        ):
            session.loaded_context.users[customer_id] = user_record.observation

        # 步骤3：进线预查一次订单（显式 tool 调用，非自动 pop）
        orders_record = self._gateway.execute(
            state=session,
            tool_name="list_user_orders",
            arguments={"user_id": customer_id},
        )
        order_count = 0
        if orders_record.status == "success" and isinstance(
            orders_record.observation, list
        ):
            for order_summary in orders_record.observation:
                if isinstance(order_summary, dict):
                    oid = order_summary.get("order_id")
                    if oid:
                        session.loaded_context.orders[oid] = order_summary
                        order_count += 1

        # 步骤4：记录 trace
        session.add_step(
            "screen_pop",
            user_id=customer_id,
            order_count=order_count,
        )
