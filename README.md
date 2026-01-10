# Traxon Core

![CI](https://github.com/adrianbenavides/traxon_core/actions/workflows/main.yml/badge.svg)
![OSV scan](https://github.com/adrianbenavides/traxon_core/actions/workflows/osv-scan.yml/badge.svg)

> [!WARNING]
> This project is currently in **Beta**. It is under active development and should **not** be used in production trading
> systems.

## Project Overview

Type-safe data models and utilities for executing retail crypto trading strategies.

## Getting Started

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

## Development & Contributing

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
