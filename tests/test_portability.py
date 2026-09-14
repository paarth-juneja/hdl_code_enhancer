from pathlib import Path

from orchestrator.config import load_project


ROOT = Path(__file__).resolve().parents[1]


def test_default_manifest_resolves_checkout_relative_tools() -> None:
    config = load_project(ROOT / "nebula.project.yaml")
    assert Path(config.tool_binary("yosys")) == (ROOT / "tools/bin/yosys").resolve()
    assert Path(config.tool_binary("opensta")) == (ROOT / "tools/bin/sta").resolve()
    assert Path(config.tool_binary("eqy")) == (ROOT / "tools/bin/eqy").resolve()
    assert Path(config.tool_binary("orfs")) == (ROOT / "tools/bin/make").resolve()


def test_checked_in_manifests_have_no_developer_home_paths() -> None:
    manifests = [
        ROOT / "nebula.project.yaml",
        *sorted((ROOT / "benchmarks").glob("*/nebula.project.yaml")),
        ROOT / "rtl_benchmark_run/nebula.project.yaml",
    ]
    for manifest in manifests:
        assert "/home/juneja" not in manifest.read_text(encoding="utf-8")


def test_tool_wrappers_discover_checkout_root() -> None:
    for wrapper in sorted((ROOT / "tools/bin").iterdir()):
        text = wrapper.read_text(encoding="utf-8")
        assert "/home/juneja" not in text
        assert "NEBULA_REPO_ROOT" in text
