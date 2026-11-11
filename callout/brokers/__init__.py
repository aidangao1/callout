"""Broker adapters. The engine only sees the Broker interface in base.py; make_broker picks one."""

from __future__ import annotations

from ..config import Config
from .base import Broker, BrokerError, ContractRef, OrderResult


def make_broker(cfg: Config, use_sim: bool = False, allow_live: bool = False, on_event=None) -> Broker:
    """The simulator for --sim (or broker type "sim"), otherwise Interactive Brokers."""
    if use_sim or cfg.broker.type == "sim":
        from .sim import SimBroker

        return SimBroker()
    from .ibkr import IBKRBroker  # imported lazily so sim/tests don't need ib_async

    return IBKRBroker(cfg.broker, allow_live=allow_live, on_event=on_event)


__all__ = ["Broker", "BrokerError", "ContractRef", "OrderResult", "make_broker"]
