# Traxon Core

![CI](https://github.com/adrianbenavides/traxon_core/actions/workflows/main.yml/badge.svg)
![OSV scan](https://github.com/adrianbenavides/traxon_core/actions/workflows/osv-scan.yml/badge.svg)

> [!WARNING]
> This project is currently in **Beta**. It is under active development and should **not** be used in production trading
> systems.

## 🔭 Project Overview

`traxon-core` is a foundational utility library that provides high-performance, type-safe, and reliable shared logic,
data models, and utility functions for executing retail crypto trading strategies.

### ✨ Key Capabilities

- **Type-Safe CCXT Abstraction:** We tame the "CCXT beast" by providing a wrapper that enforces proper data models and
  compile-time checks, replacing error-prone raw dictionary manipulation with strict typing.
- **Extensible Order Execution:** A robust engine designed for complex multi-exchange strategies (e.g., Funding Rate
  Arbitrage), simplifying the coordination and execution of orders across different venues.
- **Market-Aware Date Utilities:** High-performance, object-oriented date and time handling integrated with
  `exchange-calendars` for managing holidays, trading hours, and timezones across global markets.
- **Precision Math:** A dedicated suite of floating-point utilities ensures financial calculations are safe from
  precision errors.
- **Unified Portfolio Models:** Centralized domain models and fetchers for Spot and Perp portfolios normalize data,
  allowing strategies to interact with any exchange using a single, consistent interface.
- **Configuration Management:** Hierarchical YAML-based configuration with environment overrides and Pydantic-powered
  validation.

### 🛡️ Python & Type Safety

We leverage modern **Python 3.12+** features to build a robust and crash-resistant trading system. The codebase
prioritizes strict correctness through comprehensive type safety and validation:

- **Static Analysis:** We use **Mypy** in strict mode to enforce type correctness at compile time, catching errors
  before code is ever run.
- **Runtime Validation:** **Pydantic** models ensure that all data flowing through the system—from config files to API
  responses—conforms to strict schemas.
- **Runtime Checking:** Critical components are protected by **Beartype**, providing fast O(1) runtime type checking to
  catch type violations during execution.
- **PEP 561 Compliance:** The package is fully typed and ships with `py.typed`, ensuring that any project consuming
  `traxon-core` benefits from full type checking and auto-completion.
- **Explicit Error Handling:** We follow a **fail-fast** philosophy where functions raise explicit exceptions instead of
  returning invalid states (like `None`, `0`, or empty strings). This ensures that errors are handled immediately and
  never propagate silently through the system.

## 🏁 Getting Started

### Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)**

### Installation

#### How to Install

To install `traxon-core` as a dependency in your project:

```bash
uv add git+<repository-url>
```

#### For Contributors

To set up the development environment:

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd traxon-core
   ```

2. **Sync dependencies:**
   ```bash
   uv sync
   ```

## 🛠️ Development & Contributing

### Running Tests

To run the test suite:

```bash
uv run pytest
```

### Code Formatting

Ensure your code is formatted correctly before committing:

```bash
uv run poe format
```

### Contributing

1. Fork the repository.
2. Create a feature branch.
3. Commit your changes.
4. Push to the branch.
5. Open a Pull Request.
