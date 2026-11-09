from callout.brokers.ibkr_messages import plain_from_raw, plain_reason, split_raw

MARGIN = ("Error 201, reqId 13: Order rejected - reason:YOUR ORDER IS NOT ACCEPTED. IN ORDER TO OBTAIN THE DESIRED "
          "POSITION YOUR EQUITY WITH LOAN VALUE [741203.50 USD] MUST EXCEED THE INITIAL MARGIN [1126725.00 USD], "
          "contract: Future(conId=1, symbol='ES')")


def test_split_raw():
    code, text = split_raw(MARGIN)
    assert code == 201 and text.startswith("Order rejected - reason:YOUR ORDER") and "contract:" not in text


def test_margin_is_plain():
    assert plain_from_raw(MARGIN) == "Not enough buying power for this order."


def test_other_known_reasons():
    assert plain_reason(201, "Order rejected - reason:No trading permissions for this contract") == \
        "This account doesn't have permission to trade this contract."
    assert plain_reason(321, "The API interface is currently in Read-Only mode.").startswith("TWS is set to read-only")
    assert plain_reason(200, "No security definition has been found for the request") == \
        "IBKR doesn't recognize this contract."
    assert plain_reason(10168, "Requested market data is not subscribed.").startswith("This account has no market data")


def test_unknown_reason_is_tidied_not_lost():
    out = plain_reason(201, "Order rejected - reason:SOMETHING UNUSUAL HAPPENED")
    assert out == "IBKR: Something unusual happened."
    long = plain_reason(999, "x " * 200)
    assert long.startswith("IBKR: ") and len(long) < 180
    assert plain_reason(None, "") == "IBKR rejected the order."
