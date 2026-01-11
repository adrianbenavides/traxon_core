import subprocess
from pathlib import Path


def test_mypy_discovery_succeeds_with_py_typed():
    # Create a mock consumer script
    consumer_script = Path("consumer_mock.py")
    # We use a known function from traxon_core.dates and pass an invalid type
    consumer_script.write_text(
        "from traxon_core import dates\nimport datetime\n\n# Correct usage\ndates.to_rfc3339(datetime.datetime.now())\n\n# Incorrect usage - should trigger mypy error if types are discovered\nx: str = dates.to_rfc3339(None)\n"
    )

    try:
        # Run mypy on the mock consumer
        result = subprocess.run(
            ["uv", "run", "mypy", str(consumer_script), "--no-incremental"], capture_output=True, text=True
        )

        # If py.typed is working, mypy SHOULD discover the types and report an error
        # for the 'None' argument, instead of saying it's skipping the module.
        assert 'Argument 1 to "to_rfc3339" has incompatible type "None"' in result.stdout
        assert "error: Skipping analyzing 'traxon_core'" not in result.stdout
    finally:
        if consumer_script.exists():
            consumer_script.unlink()
