Feature: Order Executor Walking Skeleton
  As a strategy developer (Alejandro),
  I want to submit a single market order through the order executor
  so that I receive an execution report confirming the fill
  with the exchange and latency information I need to track performance.

  This walking skeleton exercises one thin vertical slice end-to-end:
    OrderRouter -> ExchangeSession -> RestOrderExecutor -> ExecutionReport
  The exchange API is mocked. All internal components are real.

  Background:
    Given the executor is configured with strategy "FAST" and max_spread_pct 0.01
    And a mock exchange "bybit" is available with REST support only

  @walking_skeleton
  Scenario: Strategy developer submits a single market order and receives an enriched execution report
    Given Alejandro has an order to buy 0.1 BTC/USDT on bybit as a taker
    When he submits the order batch through the order executor
    Then the execution report confirms the order filled on bybit
    And the execution report includes the exchange identifier "bybit"
    And the execution report includes a non-negative fill latency in milliseconds
    And the pairing is marked as filled
