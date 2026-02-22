Feature: Configurable Timeout and Symmetric Taker Fallback — M3 (US-03)
  As a strategy developer (Alejandro),
  I want the timeout duration to come from my configuration
  and for both the WebSocket and REST executors to fall back to a taker order
  when a maker order times out, so that positions are not left open indefinitely.

  Background:
    Given the executor is configured with strategy "BEST_PRICE" and max_spread_pct 0.005

  # ─── AC-03-01: timeout_duration read from config ─────────────────────────────

  @milestone_3 @us_03 @ac_03_01
  @pytest.mark.skip(reason="pending implementation: ExecutorConfig.timeout_duration field")
  Scenario: The executor respects a 90-second timeout configured by the strategy developer
    Given Alejandro configures the executor with a timeout of 90 seconds
    And a BTC/USDT maker order has been open for 91 seconds without filling
    When the timeout check runs
    Then the order is considered timed out after 90 seconds, not 300 seconds

  # ─── AC-03-02: check_timeout reads config ───────────────────────────────────

  @milestone_3 @us_03 @ac_03_02
  @pytest.mark.skip(reason="pending implementation: OrderExecutorBase.check_timeout reads config")
  Scenario: A maker order that exceeds the configured timeout triggers an order timeout
    Given Alejandro configures the executor with a timeout of 60 seconds
    And a SOL/USDT maker order was submitted 61 seconds ago
    When the timeout check runs during monitoring
    Then an order timeout is signalled for SOL/USDT

  # ─── AC-03-03: WS executor taker fallback ───────────────────────────────────

  @milestone_3 @us_03 @ac_03_03
  @pytest.mark.skip(reason="pending implementation: WsOrderExecutor taker fallback")
  Scenario: A maker order on a WebSocket exchange that times out falls back to a taker order
    Given Alejandro has an ETH/USDT maker order on bybit via WebSocket
    And the order has been open for longer than the configured timeout
    When the timeout is triggered
    Then the open limit order is cancelled
    And a taker market order is submitted for the remaining ETH/USDT amount
    And the execution report reflects the market fill
    And a structured event is emitted with the reason "maker timeout taker fallback"

  # ─── AC-03-04: Taker fallback defined once ──────────────────────────────────

  @milestone_3 @us_03 @ac_03_04
  @pytest.mark.skip(reason="pending implementation: shared execute_taker_fallback in base")
  Scenario: Taker fallback on a REST exchange follows the same behaviour as on a WebSocket exchange
    Given a SOL/USDT maker order on a REST-only exchange times out after 90 seconds
    When the timeout is triggered
    Then the open limit order is cancelled
    And a taker market order is submitted for the remaining SOL/USDT amount
    And the execution report reflects the market fill with the same fields as the WebSocket fallback

  # ─── AC-03-05: Structured log event on fallback ──────────────────────────────

  @milestone_3 @us_03 @ac_03_05
  @pytest.mark.skip(reason="pending implementation: OrderEventBus maker_timeout_taker_fallback event")
  Scenario: When a maker order times out and falls back to taker, a structured event is emitted
    Given a BTC/USDT maker order times out and the taker fallback runs
    When the fallback completes
    Then a structured event named "maker_timeout_taker_fallback" is emitted
    And the event includes the symbol, exchange, and the duration the maker was open

  # ─── Error path: taker fallback itself fails ────────────────────────────────

  @milestone_3 @us_03 @error_path
  @pytest.mark.skip(reason="pending implementation: taker fallback failure path")
  Scenario: When the taker fallback order is rejected by the exchange, the failure is reported clearly
    Given a BTC/USDT maker order has timed out on bybit
    And the taker market order is rejected by bybit with "insufficient balance"
    When the taker fallback attempt fails
    Then the pairing is marked as failed
    And a structured event is emitted capturing both the timeout and the taker rejection
    And the error propagates with a clear reason describing the taker failure

  # ─── Boundary: default timeout is 5 minutes ─────────────────────────────────

  @milestone_3 @us_03 @boundary
  @pytest.mark.skip(reason="pending implementation: ExecutorConfig default timeout")
  Scenario: When no timeout is configured, the executor uses a 5-minute default
    Given Alejandro creates an executor configuration without specifying a timeout
    When the executor checks the timeout configuration
    Then the timeout is 5 minutes
