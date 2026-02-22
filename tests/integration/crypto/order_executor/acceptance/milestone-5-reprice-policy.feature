Feature: Intelligent Reprice Policy — M5 (US-05)
  As a strategy developer (Alejandro),
  I want the executor to suppress cancel-and-replace cycles when the price movement
  is too small to justify the exchange interaction cost,
  so that my rate-limit budget is not wasted on micro-oscillations.

  Background:
    Given the executor is configured with strategy "BEST_PRICE" and max_spread_pct 0.005
    And a mock exchange "bybit" is available

  # ─── AC-05-01: min_reprice_threshold_pct config field ───────────────────────

  @milestone_5 @us_05 @ac_05_01
  @pytest.mark.skip(reason="pending implementation: ExecutorConfig.min_reprice_threshold_pct field")
  Scenario: The executor accepts a minimum reprice threshold in its configuration
    Given Alejandro configures the executor with a minimum reprice threshold of 0.1%
    When the executor is initialised
    Then the configuration is accepted with min_reprice_threshold_pct equal to 0.001
    And the default value is 0.0 when no threshold is specified

  # ─── AC-05-02: Reprice suppressed when below threshold ──────────────────────

  @milestone_5 @us_05 @ac_05_02
  @pytest.mark.skip(reason="pending implementation: RepricePolicy.should_reprice() gate")
  Scenario: A micro price movement below the threshold does not trigger cancel-and-replace
    Given a BTC/USDT maker order is at price 43200.00 on bybit
    And the executor is configured with a minimum reprice threshold of 0.1%
    When the order book emits a new best price of 43200.20 (a change of 0.00046%)
    Then no cancel_order call is made on the exchange
    And the executor remains in the monitoring state
    And a structured event is emitted noting that the reprice was suppressed

  # ─── AC-05-02: Reprice fires when above threshold ───────────────────────────

  @milestone_5 @us_05 @ac_05_02
  @pytest.mark.skip(reason="pending implementation: RepricePolicy.should_reprice() above threshold")
  Scenario: A significant price movement above the threshold triggers cancel-and-replace
    Given a BTC/USDT maker order is at price 43200.00 on bybit
    And the executor is configured with a minimum reprice threshold of 0.1%
    When the order book emits a new best price of 43140.00 (a change of 0.139%)
    Then the open order is cancelled
    And a new limit order is placed at 43140.00
    And a structured event named "order_repriced" is emitted with the old and new prices

  # ─── AC-05-03: Suppressed reprice emits DEBUG event ─────────────────────────

  @milestone_5 @us_05 @ac_05_03
  @pytest.mark.skip(reason="pending implementation: order_reprice_suppressed event")
  Scenario: When a reprice is suppressed a debug event records the price change and threshold
    Given a BTC/USDT maker order is at price 43200.00
    And the executor is configured with a minimum reprice threshold of 0.1%
    When the order book emits a price of 43200.20 (change 0.00046%)
    Then a structured event named "order_reprice_suppressed" is emitted
    And the event includes the actual price change percentage
    And the event includes the configured threshold percentage

  # ─── AC-05-04: Elapsed time override bypasses threshold ─────────────────────

  @milestone_5 @us_05 @ac_05_04
  @pytest.mark.skip(reason="pending implementation: ElapsedTimeRepricePolicy override")
  Scenario: After the elapsed override time any price change triggers a reprice regardless of threshold
    Given a BTC/USDT maker order has been open for 95 seconds
    And the executor is configured with a minimum reprice threshold of 0.1%
    And the elapsed time override is set to 90 seconds
    When the order book emits a new best price that differs by only 0.00046%
    Then the open order is cancelled despite the movement being below the threshold
    And the reprice event includes the reason "elapsed_override"

  # ─── AC-05-05: Policy logic in one place ─────────────────────────────────────

  @milestone_5 @us_05 @ac_05_05
  @pytest.mark.skip(reason="pending implementation: RepricePolicy consulted by both executors")
  Scenario: The same reprice decision applies to both WebSocket and REST executors
    Given identical BTC/USDT maker orders are active — one monitored via WebSocket and one via REST
    And both are configured with a minimum reprice threshold of 0.1%
    When both order books emit a micro price movement of 0.00046%
    Then neither order triggers a cancel-and-replace
    And both emit a reprice-suppressed event with the same threshold

  # ─── Boundary: threshold of 0.0 always reprices ──────────────────────────────

  @milestone_5 @us_05 @boundary
  @pytest.mark.skip(reason="pending implementation: RepricePolicy default behaviour")
  Scenario: When the threshold is 0.0 every price change triggers a reprice preserving existing behaviour
    Given the executor is configured with the default minimum reprice threshold of 0.0%
    And a BTC/USDT maker order is at price 43200.00
    When the order book emits any different price
    Then the order is repriced without suppression
