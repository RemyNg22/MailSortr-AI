from pathlib import Path

import pytest

from mailsortr.config import ConfigError, load_config, parse_config

EXAMPLE = Path(__file__).parent.parent / "config" / "categories.example.yaml"


def make(count: int) -> dict:
    return {
        "categories": [
            {"id": f"CAT{i}", "name": f"Cat {i}", "description": "Some description"}
            for i in range(count)
        ]
    }


def test_example_file_is_valid():
    config = load_config(EXAMPLE)
    assert 2 <= len(config.categories) <= 15
    assert config.simulate is True


def test_fifteen_categories_ok_sixteen_rejected():
    assert len(parse_config(make(15)).categories) == 15
    with pytest.raises(ConfigError):
        parse_config(make(16))


def test_remote_url_is_rejected():
    data = make(2)
    data["llm"] = {"model": "qwen3:4b", "base_url": "https://api.example.com"}
    with pytest.raises(ConfigError):
        parse_config(data)


def test_lan_url_is_rejected():
    data = make(2)
    data["llm"] = {"model": "qwen3:4b", "base_url": "http://192.168.1.20:11434"}
    with pytest.raises(ConfigError):
        parse_config(data)


def test_duplicate_id_rejected():
    data = make(2)
    data["categories"][1]["id"] = "CAT0"
    with pytest.raises(ConfigError):
        parse_config(data)