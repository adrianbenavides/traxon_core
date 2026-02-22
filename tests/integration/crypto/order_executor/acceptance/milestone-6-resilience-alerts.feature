Feature: WebSocket Resilience and Enhanced Telegram Alerts — M6 (US-06, US-07)
  As an ops engineer (Priya),
  I want the executor to automatically recover from WebSocket failures using backoff,
  fall back to REST polling when the WebSocket circuit opens,
  and send Telegram alerts that tell me which orders failed and why —
  so that I can act on problems from my phone without SSH access.

  Background:
    Given the executor is configured with strategy "BEST_PRICE" and max_spread_pct 0.005
    And a mock exchange "bybit" is available with WebSocket support

  # ─── AC-06-01: Exponential backoff on WS disconnect ─────────────────────────

  @milestone_6 @us_06 @ac_06_01
  @pytest.mark.skip(reason="pending implementation: WsOrderExecutor exponential backoff")
  Scenario: When the WebSocket stream disconnects the executor waits before reconnecting
    Given a BTC/USDT maker order is open and monitored via WebSocket on bybit
    And the order book stream raises a network error
    When the executor detects the disconnect
    Then the first reconnect attempt is delayed by approximately 100 milliseconds
    And a structured event named "ws_reconnect_attempt" is emitted with attempt number 1

  @milestone_6 @us_06 @ac_06_01
  @pytest.mark.skip(reason="pending implementation: WsOrderExecutor backoff doubling")
  Scenario: Each successive WebSocket reconnect failure doubles the wait time up to a 30 second cap
    Given the WebSocket stream has failed twice and will fail a third time
    When the executor retries the connection
    Then the second reconnect delay is approximately 200 milliseconds
    And the third reconnect delay is approximately 400 milliseconds
    And delays do not exceed 30 seconds regardless of failure count

  # ─── AC-06-02: Circuit opens after max failures ──────────────────────────────

  @milestone_6 @us_06 @ac_06_02
  @pytest.mark.skip(reason="pending implementation: WsOrderExecutor circuit breaker")
  Scenario: After the maximum number of consecutive WebSocket failures the circuit opens
    Given the executor is configured with a maximum of 3 WebSocket reconnect attempts
    And the WebSocket stream fails 3 consecutive times
    When the third failure occurs
    Then no further WebSocket reconnect attempts are made
    And a structured event named "ws_circuit_open" is emitted with the exchange identifier

  # ─── AC-06-03: REST fallback after circuit opens ─────────────────────────────

  @milestone_6 @us_06 @ac_06_03
  @pytest.mark.skip(reason="pending implementation: REST polling fallback on circuit open")
  Scenario: After the WebSocket circuit opens the executor monitors orders via REST polling
    Given the WebSocket circuit has opened for bybit after 3 failures
    And a BTC/USDT order remains open
    When the executor continues monitoring
    Then the executor calls fetch_order for the open order on bybit
    And no further WebSocket connection attempts are made for this batch
    And a structured event named "ws_rest_fallback" is emitted

  # ─── AC-06-04: Staleness window triggers REST check ──────────────────────────

  @milestone_6 @us_06 @ac_06_04
  @pytest.mark.skip(reason="pending implementation: WsOrderExecutor staleness check")
  Scenario: When no WebSocket event arrives for longer than the staleness window a REST check fires
    Given the executor is configured with a WebSocket staleness window of 10 seconds
    And a BTC/USDT order "ord-99fc12" is open on bybit
    And no WebSocket update has been received for 12 seconds
    When the staleness window expires
    Then a REST fetch_order call is made for "ord-99fc12"
    And if the REST response shows the order as filled the executor returns the execution report
    And a structured event named "ws_staleness_fallback" is emitted with the elapsed time

  # ─── AC-06-05: Staleness check does not cancel the order ─────────────────────

  @milestone_6 @us_06 @ac_06_05
  @pytest.mark.skip(reason="pending implementation: staleness fallback without cancel")
  Scenario: The staleness REST check does not cancel the open order
    Given a BTC/USDT order is open and the staleness window has elapsed
    When the staleness REST check runs
    Then no cancel_order call is made on the exchange
    And the open order remains active on the exchange

  # ─── AC-06-06: All backoff events emit structured logs ───────────────────────

  @milestone_6 @us_06 @ac_06_06
  @pytest.mark.skip(reason="pending implementation: WS resilience structured events")
  Scenario: WebSocket reconnect attempts emit structured events with attempt and delay information
    Given the WebSocket stream fails on bybit
    When the executor attempts to reconnect
    Then a structured event named "ws_reconnect_attempt" is emitted
    And the event includes the attempt number and the delay in milliseconds

  # ─── AC-07-01: Batch completion message with per-outcome counts ──────────────

  @milestone_6 @us_07 @ac_07_01
  @pytest.mark.skip(reason="pending implementation: TelegramSink structured batch summary")
  Scenario: The Telegram alert after a batch with mixed outcomes shows counts for each outcome type
    Given a batch of 5 orders completes — 3 filled, 1 timed out, 1 rejected
    When the batch completion notification is sent
    Then the Telegram message contains the text "3/5 filled"
    And the message includes a count for timeouts
    And the message includes a count for rejections

  # ─── AC-07-02: Per-order filled lines in alert ───────────────────────────────

  @milestone_6 @us_07 @ac_07_02
  @pytest.mark.skip(reason="pending implementation: TelegramSink per-order filled lines")
  Scenario: The Telegram alert includes a summary line for each filled order
    Given 2 orders fill — BTC/USDT on bybit and ETH/USDT on hyperliquid
    When the batch completion notification is sent
    Then the Telegram message includes a line for BTC/USDT@bybit with fill price and latency
    And the message includes a line for ETH/USDT@hyperliquid with fill price and latency

  # ─── AC-07-03: Per-order failure lines in alert ──────────────────────────────

  @milestone_6 @us_07 @ac_07_03
  @pytest.mark.skip(reason="pending implementation: TelegramSink per-order failure lines")
  Scenario: The Telegram alert includes a detail line for each failed order with the reason
    Given a batch where ETH/USDT on hyperliquid timed out and SOL/USDT on bybit was rejected
    When the batch completion notification is sent
    Then the Telegram message includes a failure line for ETH/USDT@hyperliquid with reason "timeout"
    And the message includes a failure line for SOL/USDT@bybit with reason "rejected"

  # ─── AC-07-04: Orphaned orders in alert ─────────────────────────────────────

  @milestone_6 @us_07 @ac_07_04
  @pytest.mark.skip(reason="pending implementation: TelegramSink orphaned order lines")
  Scenario: When an order references an unknown exchange the Telegram alert shows it as orphaned
    Given an order for BTC/USDT references exchange "kucoin" which is not in the session
    When the batch completes
    Then the Telegram message includes an orphaned line for BTC/USDT@kucoin
    And Priya can see which position needs attention without accessing server logs

  # ─── AC-07-05: Message is formatted text ─────────────────────────────────────

  @milestone_6 @us_07 @ac_07_05
  @pytest.mark.skip(reason="pending implementation: TelegramSink formatted text output")
  Scenario: The Telegram notification is human-readable text not a raw data structure
    Given a batch of orders completes
    When the Telegram notification is generated
    Then the notification text does not contain Python type representations
    And the notification text does not contain raw dictionary braces
    And Priya can read and act on the notification from her phone
