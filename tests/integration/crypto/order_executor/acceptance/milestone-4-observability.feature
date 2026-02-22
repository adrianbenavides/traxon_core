Feature: Observability — State Events and Enriched Reports — M4 (US-04, US-08)
  As an ops engineer (Priya) and strategy developer (Alejandro),
  I want every order state transition to emit a structured event with a consistent schema
  and every execution report to include the originating exchange and fill latency,
  so that I can reconstruct what happened without digging through unstructured logs
  and Alejandro can track execution quality per exchange.

  Background:
    Given the executor is configured with strategy "BEST_PRICE" and max_spread_pct 0.005
    And a mock exchange "bybit" is available

  # ─── AC-04-01: Canonical event names ────────────────────────────────────────

  @milestone_4 @us_04 @ac_04_01
  @pytest.mark.skip(reason="pending implementation: OrderEventBus canonical event names")
  Scenario: All canonical event names are emitted during a successful maker order lifecycle
    Given Alejandro submits a BTC/USDT maker order on bybit that fills successfully
    When the order completes
    Then the event log contains an event named "order_submitted"
    And the event log contains an event named "order_fill_complete"
    And every event includes the order identifier as a correlation field

  @milestone_4 @us_04 @ac_04_01
  @pytest.mark.skip(reason="pending implementation: order_repriced event")
  Scenario: A reprice event is emitted when the order is cancelled and resubmitted at a new price
    Given a BTC/USDT maker order at price 43200.00 is open on bybit
    And the order book shifts significantly to a new best price of 43140.00
    When the executor reprices the order
    Then a structured event named "order_repriced" is emitted
    And the event includes the previous price 43200.00 and the new price 43140.00

  @milestone_4 @us_04 @ac_04_01
  @pytest.mark.skip(reason="pending implementation: order_spread_blocked event")
  Scenario: A spread-blocked event is emitted when order placement is delayed by a wide spread
    Given the BTC/USDT spread is 0.80% which exceeds the configured maximum of 0.50%
    When the executor waits for the spread to normalise
    Then a structured event named "order_spread_blocked" is emitted
    And the event includes the current spread percentage and elapsed waiting time

  # ─── AC-04-02: Required fields on every event ───────────────────────────────

  @milestone_4 @us_04 @ac_04_02
  @pytest.mark.skip(reason="pending implementation: OrderEvent required fields")
  Scenario: Every structured event includes the required correlation and timing fields
    Given Alejandro submits a BTC/USDT maker order on bybit
    When the order goes through any state transition
    Then every emitted event includes:
      | field        | description                          |
      | order_id     | unique correlation key for the order |
      | symbol       | the trading pair                     |
      | exchange_id  | which exchange the order is on       |
      | timestamp_ms | epoch milliseconds at emission time  |

  # ─── AC-04-03: fill_latency_ms in order_fill_complete ───────────────────────

  @milestone_4 @us_04 @ac_04_03
  @pytest.mark.skip(reason="pending implementation: fill_latency_ms in fill complete event")
  Scenario: The fill completion event includes the time from submission to filled status
    Given a BTC/USDT maker order was submitted at a known time
    And the exchange confirms the fill 2850 milliseconds later
    When the order_fill_complete event is emitted
    Then the event includes fill_latency_ms equal to 2850
    And fill_latency_ms is greater than zero

  # ─── AC-04-04: Partial fill events during monitoring ────────────────────────

  @milestone_4 @us_04 @ac_04_04
  @pytest.mark.skip(reason="pending implementation: order_fill_partial event")
  Scenario: A partial fill event is emitted when the exchange reports a partial fill
    Given a BTC/USDT maker order for 1.0 BTC is open on bybit
    And the exchange reports that 0.6 BTC has been filled with 0.4 BTC remaining
    When the order status update is processed
    Then a structured event named "order_fill_partial" is emitted
    And the event shows 0.6 filled and 0.4 remaining
    And the executor continues monitoring for the remaining 0.4 BTC

  # ─── AC-04-05: Consistent schema across WS and REST ─────────────────────────

  @milestone_4 @us_04 @ac_04_05
  @pytest.mark.skip(reason="pending implementation: unified event schema")
  Scenario: Events from WebSocket and REST executors use identical field names
    Given identical BTC/USDT buy orders are submitted — one on a WebSocket exchange and one on a REST exchange
    When both orders fill successfully
    Then the order_submitted event from both executors has the same fields
    And the order_fill_complete event from both executors has the same fields
    And no field name differs between the WebSocket and REST outputs

  # ─── AC-08-01: exchange_id in ExecutionReport ───────────────────────────────

  @milestone_4 @us_08 @ac_08_01
  @pytest.mark.skip(reason="pending implementation: ExecutionReport.exchange_id field")
  Scenario: The execution report includes the exchange identifier after a fill on bybit
    Given a BTC/USDT maker order fills on bybit
    When the execution report is produced
    Then the report includes exchange_id equal to "bybit"
    And the exchange_id field is not empty

  # ─── AC-08-02: fill_latency_ms in ExecutionReport ───────────────────────────

  @milestone_4 @us_08 @ac_08_02
  @pytest.mark.skip(reason="pending implementation: ExecutionReport.fill_latency_ms field")
  Scenario: The execution report includes fill latency from submission to closed status
    Given a BTC/USDT maker order was submitted at a known time and fills 2850 milliseconds later
    When the execution report is produced
    Then the report includes fill_latency_ms equal to 2850
    And fill_latency_ms is zero or greater

  # ─── AC-08-03: Reports from multiple exchanges distinguishable ───────────────

  @milestone_4 @us_08 @ac_08_03
  @pytest.mark.skip(reason="pending implementation: multi-exchange report disambiguation")
  Scenario: Reports from two exchanges for the same symbol are distinguishable by exchange identifier
    Given Alejandro submits BTC/USDT buy on bybit and BTC/USDT sell on hyperliquid
    When both orders fill and their reports are returned
    Then one report has exchange_id "bybit"
    And the other report has exchange_id "hyperliquid"
    And neither report has an empty exchange_id

  # ─── AC-08-06: ExecutionReport remains immutable ─────────────────────────────

  @milestone_4 @us_08 @ac_08_06
  @pytest.mark.skip(reason="pending implementation: ExecutionReport frozen model")
  Scenario: The execution report cannot be modified after it is created
    Given an execution report has been produced for a filled BTC/USDT order
    When an attempt is made to change the exchange_id field on the report
    Then a validation error is raised
    And the original report is unchanged
