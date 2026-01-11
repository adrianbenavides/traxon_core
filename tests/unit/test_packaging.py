import tomllib
from pathlib import Path


def test_pyproject_includes_py_typed():
    pyproject_path = Path("pyproject.toml")
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    # We verify that there is an explicit include for the marker file
    tool = data.get("tool", {})
    hatch = tool.get("hatch", {})
    build = hatch.get("build", {})

    # We expect either a global include or a wheel specific include
    include = build.get("include", [])
    wheel_include = build.get("targets", {}).get("wheel", {}).get("include", [])
    force_include = build.get("targets", {}).get("wheel", {}).get("force-include", {})

    all_includes = include + wheel_include + list(force_include.keys())

    assert any("py.typed" in s for s in all_includes), "pyproject.toml does not explicitly include py.typed"
