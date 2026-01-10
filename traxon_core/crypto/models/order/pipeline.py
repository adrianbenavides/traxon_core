from collections import defaultdict
from typing import Any

import polars as pl
from beartype import beartype

from traxon_core.crypto.models.symbol import BaseQuote
from traxon_core.logs.notifiers import notifier
from traxon_core.logs.structlog import logger

from .builder import OrderBuilder
from .exceptions import OrderValidationError
from .request import OrderRequest


class OrdersToExecute:
    """
    A list of orders to be executed.

    Processing flow:
    1. Validates OrderBuilder objects and converts them to OrderRequest objects.
    2. Prioritizes 'updates' (existing position adjustments) over 'new' orders.
    3. Deduplicates 'new' orders against 'updates' to avoid redundant operations.
    """

    updates: dict[BaseQuote, list[OrderRequest]]
    new: dict[BaseQuote, list[OrderRequest]]

    @beartype
    def __init__(
        self,
        updates: dict[BaseQuote, list[OrderBuilder]],
        new: dict[BaseQuote, list[OrderBuilder]],
    ) -> None:
        self.updates = self._process_orders(updates, "updates")
        self.new = self._process_orders(new, "new")
        self._deduplicate_new_orders()

    @beartype
    def count(self) -> int:
        return sum(len(orders) for orders in self.updates.values()) + sum(
            len(orders) for orders in self.new.values()
        )

    @beartype
    def _process_orders(
        self,
        orders_by_base_quote: dict[BaseQuote, list[OrderBuilder]],
        list_name: str,
    ) -> dict[BaseQuote, list[OrderRequest]]:
        """
        Validates builders and converts them to requests.
        If any order in a group (list) fails validation, the entire group is dropped.
        """
        valid_requests: dict[BaseQuote, list[OrderRequest]] = defaultdict(list)

        for base_quote, builders in orders_by_base_quote.items():
            requests: list[OrderRequest] = []
            group_valid = True
            failure_reasons: list[str] = []

            for builder in builders:
                try:
                    request = builder.build()
                    requests.append(request)
                except OrderValidationError as e:
                    group_valid = False
                    failure_reasons.append(str(e))
                except Exception as e:
                    group_valid = False
                    failure_reasons.append(f"Unexpected error: {e}")

            if group_valid:
                valid_requests[base_quote] = requests
            else:
                symbol_str = f"{base_quote.base}/{base_quote.quote}"
                reasons_str = "; ".join(failure_reasons)
                logger.warning(
                    f"{symbol_str} - removing from {list_name} orders due to validation errors: {reasons_str}"
                )

        return dict(valid_requests)

    @beartype
    def _deduplicate_new_orders(self) -> None:
        """
        Removes orders from 'new' that are duplicates of 'updates' or internal duplicates.
        """
        # Create a set of unique identifiers for orders in updates
        update_keys: set[str] = set()
        for requests in self.updates.values():
            for req in requests:
                # Key based on exchange, symbol, side, amount
                key = f"{req.exchange_id}:{req.symbol}:{req.side}:{req.amount}"
                update_keys.add(key)

        cleaned_new: dict[BaseQuote, list[OrderRequest]] = defaultdict(list)

        for base_quote, requests in self.new.items():
            seen_in_group: set[str] = set()
            filtered_requests: list[OrderRequest] = []

            for req in requests:
                key = f"{req.exchange_id}:{req.symbol}:{req.side}:{req.amount}"

                if key in update_keys:
                    logger.warning(
                        f"{req.symbol} - removing duplicate order from 'new' (already exists in 'updates')"
                    )
                    continue

                if key in seen_in_group:
                    logger.warning(f"{req.symbol} - removing duplicate order within 'new'")
                    continue

                seen_in_group.add(key)
                filtered_requests.append(req)

            if filtered_requests:
                cleaned_new[base_quote] = filtered_requests

        self.new = dict(cleaned_new)

    @beartype
    def is_empty(self) -> bool:
        return not self.updates and not self.new

    @beartype
    async def log_as_df(self, context: str) -> None:
        if self.updates or self.new:
            logger.info(context)
            await notifier.notify(context)

        # Helper to convert OrderRequest to dict for DataFrame
        def req_to_dict(req: OrderRequest) -> dict[str, Any]:
            return {
                "symbol": f"{req.symbol}@{req.exchange_id}",
                "side": req.side.value,
                "amount": f"{req.amount:.4f}",
                "type": req.execution_type.value,
                "notes": req.notes,
            }

        if self.updates:
            updates_df = pl.DataFrame(
                [req_to_dict(req) for reqs in self.updates.values() for req in reqs]
            ).sort("symbol")
            logger.info("update orders:", df=updates_df)
            await notifier.notify("update orders:")
            await notifier.notify(updates_df)

        if self.new:
            new_df = pl.DataFrame([req_to_dict(req) for reqs in self.new.values() for req in reqs]).sort(
                "symbol"
            )
            logger.info("new orders:", df=new_df)
            await notifier.notify("new orders:")
            await notifier.notify(new_df)
