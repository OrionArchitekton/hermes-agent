"""Fallback-provider diagnostics must never render raw credentials."""

import json
from types import SimpleNamespace

import pytest
import yaml


class _ProviderOptions:
    def __init__(self, *, secret: str) -> None:
        self.endpoint = "https://fallback.example/v1"
        self.value = secret

    def __repr__(self) -> str:
        return f"_ProviderOptions(secret={self.value!r})"


class _ExplodingFallback:
    def __init__(self, *, secret: str) -> None:
        self.secret = secret

    def __bool__(self) -> bool:
        raise RuntimeError(self.secret)

    def __repr__(self) -> str:
        return f"_ExplodingFallback(secret={self.secret!r})"


def _fallback_payload(config: dict, *, show_keys: bool = False):
    from hermes_cli import dump

    rendered = dump._config_overrides(
        config,
        show_keys=show_keys,
    )["fallback_providers"]
    return json.loads(rendered), rendered


def test_known_fallback_fields_preserve_safe_routing_and_mask_credentials():
    from hermes_cli import dump

    inline_key = "inline-opaque-secret-material-123456"
    config = {
        "fallback_providers": [
            {
                "provider": "custom",
                "model": "diagnostic-model",
                "base_url": "https://fallback.example/v1",
                "api_mode": "chat_completions",
                "transport": "openai_chat",
                "key_env": "CUSTOM_FALLBACK_API_KEY",
                "api_key": inline_key,
            },
        ],
    }

    payload, rendered = _fallback_payload(config)

    assert payload == [
        {
            "provider": "custom",
            "model": "diagnostic-model",
            "base_url": "https://fallback.example/v1",
            "api_mode": "chat_completions",
            "transport": "openai_chat",
            "key_env": "configured",
            "api_key": "set",
        },
    ]
    assert inline_key not in rendered

    shown, rendered_shown = _fallback_payload(config, show_keys=True)
    assert shown[0]["api_key"] == dump._redact(inline_key)
    assert inline_key not in rendered_shown


def test_unknown_nested_fields_are_omitted_without_traversing_or_stringifying():
    secrets = {
        "mapping": "nested-mapping-opaque-secret-material-123456",
        "list": "nested-list-opaque-secret-material-123456",
        "object": "nested-object-opaque-secret-material-123456",
        "header": "nested-header-opaque-secret-material-123456",
        "mapping_key": "sk-" + "proj-synthetic-key-material-012345",
    }
    config = {
        "fallback_providers": [
            {
                "provider": "custom",
                "model": "diagnostic-model",
                "metadata": {
                    "credential": secrets["mapping"],
                    secrets["mapping_key"]: "associated-opaque-value-123456",
                },
                "headers": [
                    ["X-Api-Key", secrets["list"]],
                    {"headerName": "Authorization", "headerValue": secrets["header"]},
                ],
                "options": _ProviderOptions(secret=secrets["object"]),
            },
        ],
    }

    for show_keys in (False, True):
        payload, rendered = _fallback_payload(config, show_keys=show_keys)

        assert payload == [
            {
                "provider": "custom",
                "model": "diagnostic-model",
                "omitted_fields": 3,
            },
        ]
        assert "metadata" not in rendered
        assert "headers" not in rendered
        assert "_ProviderOptions" not in rendered
        for secret in secrets.values():
            assert secret not in rendered


def test_unsupported_fallback_container_never_uses_truthiness_or_repr():
    secret = "exception-opaque-" + "secret-material-123456"

    payload, rendered = _fallback_payload(
        {
            "fallback_providers": _ExplodingFallback(secret=secret),
        },
    )

    assert payload == "<invalid fallback_providers>"
    assert secret not in rendered
    assert "_ExplodingFallback" not in rendered


def test_unknown_secret_fields_and_header_shapes_are_fail_closed():
    secrets = {
        "passcode": "opaque-passcode-material-123456",
        "subscription": "opaque-subscription-material-123456",
        "sas": "opaque-sas-material-123456",
        "header_map": "opaque-header-map-material-123456",
        "header_pair": "opaque-header-pair-material-123456",
        "header_record": "opaque-header-record-material-123456",
        "numeric_pin": "841927",
    }
    config = {
        "fallback_providers": [
            {
                "provider": "custom",
                "model": "diagnostic-model",
                "passcode": secrets["passcode"],
                "pin": int(secrets["numeric_pin"]),
                "subscription_key": secrets["subscription"],
                "sas": secrets["sas"],
                "extra_headers": {
                    "Ocp-Apim-Subscription-Key": secrets["header_map"],
                },
                "headers": [
                    ["X-Client-Key", secrets["header_pair"]],
                    {
                        "name": "Authorization",
                        "values": [secrets["header_record"]],
                    },
                ],
            },
        ],
    }

    for show_keys in (False, True):
        payload, rendered = _fallback_payload(config, show_keys=show_keys)

        assert payload[0]["provider"] == "custom"
        assert payload[0]["model"] == "diagnostic-model"
        assert payload[0]["omitted_fields"] == 6
        for secret in secrets.values():
            assert secret not in rendered


def test_environment_reference_fields_report_presence_without_emitting_bytes():
    env_reference = "CUSTOM_FALLBACK_API_KEY"
    literal_key = "Q7m4" + "V2p9L8s6N3x5R1c0"
    aws_access_key = "AKIA" + "ABCDEFGHIJKLMNOP"
    env_shaped_literal = "ZXCVBNM" + "1234567890_TOKEN"
    split_env_shaped_literal = "ABCD1234_EFGH5678_" + "IJKL_TOKEN"
    alpha_env_shaped_literal = "ZXCVBNMASDFGHJKLQWERTY_" + "TOKEN"
    config = {
        "fallback_providers": [
            {
                "provider": "custom",
                "model": "one",
                "key_env": env_reference,
            },
            {
                "provider": "custom",
                "model": "two",
                "key_env": literal_key,
            },
            {
                "provider": "custom",
                "model": "three",
                "api_key_env": aws_access_key,
            },
            {
                "provider": "custom",
                "model": "four",
                "key_env": env_shaped_literal,
            },
            {
                "provider": "custom",
                "model": "five",
                "key_env": split_env_shaped_literal,
            },
            {
                "provider": "custom",
                "model": "six",
                "key_env": alpha_env_shaped_literal,
            },
        ],
    }

    hidden, hidden_rendered = _fallback_payload(config)
    shown, shown_rendered = _fallback_payload(config, show_keys=True)

    for index, field in (
        (0, "key_env"),
        (1, "key_env"),
        (2, "api_key_env"),
        (3, "key_env"),
        (4, "key_env"),
        (5, "key_env"),
    ):
        assert hidden[index][field] == "configured"
        assert shown[index][field] == "configured"
    for value in (
        env_reference,
        literal_key,
        aws_access_key,
        env_shaped_literal,
        split_env_shaped_literal,
        alpha_env_shaped_literal,
    ):
        assert value not in hidden_rendered
        assert value not in shown_rendered


def test_model_ids_remain_useful_while_unstructured_tokens_are_omitted():
    opaque_token = "a1b2c3d4" * 5
    hyphenated_token = "Q7m4V2p9-" + "L8s6N3x5R1c0-secret"
    mixed_provider_value = "Ab1Cd2Ef3Gh4-" + "Ij5Kl6Mn7Op8-Qr9St0Uv1Wx2"
    uuid_value = "a1b2c3d4-e5f6-" + "a7b8-c9d0-e1f2a3b4c5d6"
    slash_value_one = "Q7m4V2p9L8s6/" + "N3x5R1c0AbCdEfGhIj"
    slash_value_two = "AbCdEfGhIjKlMnOp/" + "QrStUvWxYz012345"
    config = {
        "fallback_providers": [
            {
                "provider": opaque_token,
                "model": "Qwen/Qwen3-Coder-480B-A35B-Instruct",
            },
            {
                "provider": "custom",
                "model": opaque_token,
            },
            {
                "provider": "custom",
                "model": hyphenated_token,
            },
            {
                "provider": mixed_provider_value,
                "model": "diagnostic-model",
            },
            {
                "provider": "custom",
                "model": uuid_value,
            },
            {
                "provider": "custom",
                "model": slash_value_one,
            },
            {
                "provider": "custom",
                "model": slash_value_two,
            },
            {
                "provider": "custom",
                "model": "XiaomiMiMo/MiMo-V2-Flash",
            },
        ],
    }

    payload, rendered = _fallback_payload(config)

    assert payload[0]["provider"] == "<redacted>"
    assert payload[0]["model"] == "Qwen/Qwen3-Coder-480B-A35B-Instruct"
    assert payload[1]["provider"] == "custom"
    assert payload[1]["model"] == "<redacted>"
    assert payload[2]["provider"] == "custom"
    assert payload[2]["model"] == "<redacted>"
    assert payload[3]["provider"] == "<redacted>"
    assert payload[3]["model"] == "diagnostic-model"
    assert payload[4]["provider"] == "custom"
    assert payload[4]["model"] == "<redacted>"
    assert payload[5]["provider"] == "custom"
    assert payload[5]["model"] == "<redacted>"
    assert payload[6]["provider"] == "custom"
    assert payload[6]["model"] == "<redacted>"
    assert payload[7]["provider"] == "custom"
    assert payload[7]["model"] == "XiaomiMiMo/MiMo-V2-Flash"
    for secret in (
        opaque_token,
        hyphenated_token,
        mixed_provider_value,
        uuid_value,
        slash_value_one,
        slash_value_two,
    ):
        assert secret not in rendered


def test_base_url_omits_userinfo_query_fragment_and_opaque_paths():
    path_secret = "Q7m4" + "V2p9L8s6N3x5R1c0"
    query_secret = "opaque-query-secret-material-123456"
    hostname_secret = "a1b2c3d4" * 5
    lowercase_hostname_secret = "q7m4v2p9" + "l8s6n3x5r1c0"
    hex_hostname_value = "abcdef012345" + "6789abcd"
    config = {
        "fallback_providers": [
            {
                "provider": "custom",
                "model": "diagnostic-model",
                "base_url": (
                    "https://synthetic-user:synthetic-password@fallback.example/"
                    f"{path_secret}/v1?credential={query_secret}#private-fragment"
                ),
            },
            {
                "provider": "custom",
                "model": "diagnostic-model",
                "base_url": f"https://{hostname_secret}.invalid/v1",
            },
            {
                "provider": "custom",
                "model": "diagnostic-model",
                "base_url": f"https://{lowercase_hostname_secret}.invalid/v1",
            },
            {
                "provider": "custom",
                "model": "diagnostic-model",
                "base_url": f"https://{hex_hostname_value}.invalid/v1",
            },
        ],
    }

    for show_keys in (False, True):
        payload, rendered = _fallback_payload(config, show_keys=show_keys)

        assert payload[0]["base_url"] == "https://fallback.example/<path-omitted>"
        assert payload[1]["base_url"] == "<redacted endpoint>"
        assert payload[2]["base_url"] == "<redacted endpoint>"
        assert payload[3]["base_url"] == "<redacted endpoint>"
        assert "fallback.example" in rendered
        for secret in (
            "synthetic-user",
            "synthetic-password",
            path_secret,
            query_secret,
            "private-fragment",
            hostname_secret,
            lowercase_hostname_secret,
            hex_hostname_value,
        ):
            assert secret not in rendered


@pytest.mark.parametrize("scheme", ["Bearer", "Basic"])
def test_show_keys_masks_bare_authorization_values(scheme):
    from hermes_cli import dump

    secret = f"{scheme} " + "Q7m4" + "V2p9L8s6N3x5R1c0"
    config = {
        "fallback_providers": [
            {
                "provider": "custom",
                "model": "diagnostic-model",
                "api_key": secret,
            },
        ],
    }

    payload, rendered = _fallback_payload(config, show_keys=True)

    assert payload[0]["api_key"] == dump._redact(secret)
    assert secret not in rendered


@pytest.mark.parametrize("show_keys", [False, True])
def test_run_dump_loads_temp_config_and_never_emits_nested_plaintext(
    monkeypatch,
    capsys,
    tmp_path,
    show_keys,
):
    """Exercise config.yaml -> load_config -> run_dump -> stdout end to end."""
    from hermes_cli import dump
    from hermes_cli.config import get_hermes_home

    inline_key = "e2e-inline-opaque-secret-material-123456"
    nested_key = "e2e-nested-opaque-secret-material-123456"
    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "fallback_providers": [
                    {
                        "provider": "custom",
                        "model": "diagnostic-model",
                        "base_url": "https://fallback.example/v1",
                        "api_key": inline_key,
                        "metadata": {
                            "nested": [
                                {"credential": nested_key},
                            ],
                        },
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (home / ".env").write_text("", encoding="utf-8")
    monkeypatch.setattr(dump, "get_project_root", lambda: tmp_path / "noproject")
    monkeypatch.setattr(dump, "_gateway_status", lambda: "stopped (test)")

    dump.run_dump(SimpleNamespace(show_keys=show_keys))
    captured = capsys.readouterr()

    assert "fallback_providers" in captured.out
    assert "diagnostic-model" in captured.out
    assert "https://fallback.example/v1" in captured.out
    assert '"omitted_fields": 1' in captured.out
    if show_keys:
        assert dump._redact(inline_key) in captured.out
    else:
        assert '"api_key": "set"' in captured.out
    for secret in (inline_key, nested_key):
        assert secret not in captured.out
        assert secret not in captured.err
