"""Tests for Slack CLI helpers."""

import json
from argparse import Namespace

from hermes_cli.slack_cli import _build_full_manifest, slack_manifest_command


class TestSlackFullManifest:
    """Generated full Slack app manifest used by `hermes slack manifest`."""

    def test_app_home_messages_are_writable(self):
        manifest = _build_full_manifest("Hermes", "Your Hermes agent on Slack")

        assert manifest["features"]["app_home"] == {
            "home_tab_enabled": False,
            "messages_tab_enabled": True,
            "messages_tab_read_only_enabled": False,
        }

    def test_private_channel_directory_scope_is_included(self):
        manifest = _build_full_manifest("Hermes", "Your Hermes agent on Slack")

        bot_scopes = manifest["oauth_config"]["scopes"]["bot"]
        assert "groups:read" in bot_scopes

    def test_assistant_features_remain_enabled(self):
        manifest = _build_full_manifest("Hermes", "Your Hermes agent on Slack")

        assert "assistant_view" in manifest["features"]
        assert "assistant:write" in manifest["oauth_config"]["scopes"]["bot"]
        bot_events = manifest["settings"]["event_subscriptions"]["bot_events"]
        assert "assistant_thread_started" in bot_events

    def test_custom_request_url_reaches_native_slashes(self):
        manifest = _build_full_manifest(
            "Hermes",
            "Your Hermes agent on Slack",
            request_url="https://ops.example.com/slack/commands",
        )

        slash_urls = {
            command["url"] for command in manifest["features"]["slash_commands"]
        }
        assert slash_urls == {"https://ops.example.com/slack/commands"}

    def test_interactivity_request_url_is_optional(self):
        manifest = _build_full_manifest(
            "Hermes",
            "Your Hermes agent on Slack",
            interactivity_request_url="https://ops.example.com/slack/actions",
        )

        assert manifest["settings"]["interactivity"] == {
            "is_enabled": True,
            "request_url": "https://ops.example.com/slack/actions",
        }


class TestSlackManifestCommand:
    """CLI command output for `hermes slack manifest`."""

    def test_slashes_only_uses_custom_request_url(self, capsys):
        result = slack_manifest_command(
            Namespace(
                name=None,
                description=None,
                request_url="https://ops.example.com/slack/commands",
                interactivity_request_url=None,
                slashes_only=True,
                write=None,
            )
        )

        assert result == 0
        payload = json.loads(capsys.readouterr().out)
        assert {entry["url"] for entry in payload} == {
            "https://ops.example.com/slack/commands"
        }
