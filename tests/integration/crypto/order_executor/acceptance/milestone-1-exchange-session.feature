Feature: Exchange Session Lifecycle — M1 (US-01)
  As a strategy developer (Alejandro),
  I want the order executor to coordinate all per-exchange setup once per batch
  so that margin and leverage calls do not repeat for every individual order,
  and WebSocket connections are ready before the first order is handed to the executor.

  Background:
    Given the executor is configured with strategy "BEST_PRICE" and max_spread_pct 0.005
    And a mock exchange "bybit" is available with WebSocket support

  # ─── AC-01-01: Margin mode deduplication ────────────────────────────────────

  @milestone_1 @us_01 @ac_01_01
  @pytest.mark.skip(reason="pending implementation: ExchangeSession.initialize()")
  Scenario: Margin mode is set once per symbol even when multiple orders share that symbol
    Given Alejandro submits a batch with 5 orders on bybit — 3 for BTC/USDT and 2 for ETH/USDT
    When the order batch is submitted through the order executor
    Then the exchange receives exactly 1 set_margin_mode call for BTC/USDT on bybit
    And the exchange receives exactly 1 set_margin_mode call for ETH/USDT on bybit
    And the total set_margin_mode call count is 2, not 5

  # ─── AC-01-02: Leverage deduplication ───────────────────────────────────────

  @milestone_1 @us_01 @ac_01_02
  @pytest.mark.skip(reason="pending implementation: ExchangeSession.initialize()")
  Scenario: Leverage is configured at most once per symbol regardless of order count
    Given Alejandro configures bybit at 3x leverage
    And he submits 4 ETH/USDT maker orders on bybit
    When the order batch is submitted through the order executor
    Then the exchange receives exactly 1 set_leverage call for ETH/USDT on bybit with leverage 3
    And subsequent orders reuse the cached leverage without calling set_leverage again

  # ─── AC-01-03: WebSocket pre-warm ───────────────────────────────────────────

  @milestone_1 @us_01 @ac_01_03
  @pytest.mark.skip(reason="pending implementation: ExchangeSession.initialize() WS pre-warm")
  Scenario: WebSocket connection for a symbol is established during session initialisation before any order is submitted
    Given Alejandro has a BTC/USDT maker order on bybit which supports WebSocket
    When the order executor begins initialising the exchange session
    Then the watch_order_book stream for BTC/USDT on bybit is started during session initialisation
    And watch_order_book is active before the first create_limit_order call is made

  # ─── AC-01-04: No cross-call state ──────────────────────────────────────────

  @milestone_1 @us_01 @ac_01_04
  @pytest.mark.skip(reason="pending implementation: ExchangeSession lifecycle scoping")
  Scenario: Exchange session state is not carried over between separate order batches
    Given Alejandro submits batch 1 with a BTC/USDT order on bybit
    And batch 1 completes successfully
    When Alejandro submits batch 2 with another BTC/USDT order on bybit
    Then set_margin_mode is called again for BTC/USDT in batch 2
    And the session from batch 1 is not reused for batch 2

  # ─── AC-01-05: Public entry point unchanged ──────────────────────────────────

  @milestone_1 @us_01 @ac_01_05
  @pytest.mark.skip(reason="pending implementation: interface stability check")
  Scenario: The order executor public entry point signature remains unchanged after refactor
    Given Alejandro calls execute_orders with a list of exchanges and an OrdersToExecute batch
    When the call completes
    Then it returns a list of execution reports
    And no new public methods need to be called by Alejandro to use the executor

  # ─── AC-X-08: OrderRequest params propagated to exchange API ─────────────────

  @milestone_1 @us_01 @ac_x_08
  @pytest.mark.skip(reason="pending implementation: params propagation fix")
  Scenario: Exchange-specific parameters from the order request reach the exchange API
    Given Alejandro's order request includes exchange-specific params {"postOnly": true}
    And the order is submitted on bybit via REST
    When the order is created on the exchange
    Then create_limit_order receives the params {"postOnly": true}
    And the params are not silently dropped

  # ─── AC-X-07: notify_failed on exchange not found ────────────────────────────

  @milestone_1 @us_01 @ac_x_07
  @pytest.mark.skip(reason="pending implementation: OrderRouter exchange-not-found path")
  Scenario: An order referencing an unknown exchange notifies the pairing as failed before being skipped
    Given Alejandro submits an order for BTC/USDT on exchange "kucoin"
    And the exchanges list contains only "bybit"
    When the order batch is submitted through the order executor
    Then the pairing for the BTC/USDT@kucoin order is marked as failed
    And the batch continues processing any remaining valid orders
    And a structured event is emitted indicating the exchange was not found
