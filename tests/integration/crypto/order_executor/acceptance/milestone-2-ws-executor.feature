Feature: Event-Driven WebSocket Executor — M2 (US-02)
  As a strategy developer (Alejandro),
  I want the WebSocket order executor to react to exchange events as they arrive
  so that fill detection and reprice decisions happen within milliseconds,
  not on a 100ms polling schedule.

  Background:
    Given the executor is configured with strategy "BEST_PRICE" and max_spread_pct 0.005
    And a mock exchange "bybit" is available with WebSocket support

  # ─── AC-02-01: No busy-wait polling ─────────────────────────────────────────

  @milestone_2 @us_02 @ac_02_01
  @pytest.mark.skip(reason="pending implementation: WsOrderExecutor event-driven loop")
  Scenario: The WebSocket monitoring loop does not use sleep-based polling to detect fills
    Given a BTC/USDT maker order is open and being monitored on bybit via WebSocket
    And no order book or order status events arrive for 3 seconds
    When the monitoring loop runs during those 3 seconds
    Then the executor performs zero loop iterations during the quiet period
    And the executor resumes only when the next WebSocket event arrives

  # ─── AC-02-02: Fill detection latency below 20ms ────────────────────────────

  @milestone_2 @us_02 @ac_02_02
  @pytest.mark.skip(reason="pending implementation: WsOrderExecutor fill detection")
  Scenario: A fill is detected within one event cycle after the WebSocket message arrives
    Given a BTC/USDT maker order "ord-7f3a" is open on bybit
    When the exchange sends a WebSocket order update marking "ord-7f3a" as filled
    Then the execution report is returned within 20 milliseconds of the message being received
    And the report shows the order is filled

  # ─── AC-02-03: State machine transitions preserved ───────────────────────────

  @milestone_2 @us_02 @ac_02_03
  @pytest.mark.skip(reason="pending implementation: WsOrderExecutor state machine")
  Scenario: A maker order progresses through expected lifecycle states from submission to fill
    Given Alejandro submits a BTC/USDT maker order on bybit via WebSocket
    When the order goes through the full happy path
    Then the order transitions through: pending, submitted, monitoring, and filled
    And the structured event log records each transition with an order identifier

  # ─── AC-02-04: Concurrent streams both handled ───────────────────────────────

  @milestone_2 @us_02 @ac_02_04
  @pytest.mark.skip(reason="pending implementation: WsOrderExecutor concurrent stream handling")
  Scenario: Both the order book stream and the order status stream are monitored simultaneously
    Given a BTC/USDT maker order is open on bybit
    When a new order book snapshot arrives at the same time as an order status update
    Then both events are processed without either being dropped
    And the reprice evaluation runs on the order book event
    And the fill detection runs on the order status event

  # ─── AC-02-05: Task cleanup on exception ────────────────────────────────────

  @milestone_2 @us_02 @ac_02_05
  @pytest.mark.skip(reason="pending implementation: WsOrderExecutor task cleanup")
  Scenario: WebSocket tasks are cancelled cleanly when an error is raised mid-execution
    Given a BTC/USDT maker order is being monitored on bybit
    When an unexpected error occurs during execution
    Then the order book watch task is cancelled
    And the order status watch task is cancelled
    And no background tasks are left running after execution ends

  # ─── AC-X-05: Unified OrderState enum ───────────────────────────────────────

  @milestone_2 @us_02 @ac_x_05
  @pytest.mark.skip(reason="pending implementation: unified OrderState enum")
  Scenario: State transition events from WebSocket and REST executors use the same state names
    Given identical order requests are submitted — one on a WebSocket exchange and one on a REST exchange
    When both orders fill successfully
    Then the structured events from both executors use the same canonical state names
    And no state name differs between the WebSocket and REST event outputs
