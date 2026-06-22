from plugins.memory.atlas_estate import AtlasEstateMemoryProvider


def test_atlas_estate_provider_has_no_tools():
    provider = AtlasEstateMemoryProvider()

    assert provider.name == "atlas_estate"
    assert provider.get_tool_schemas() == []


def test_atlas_estate_prefetch_formats_hits(monkeypatch):
    provider = AtlasEstateMemoryProvider(
        {
            "base_url": "http://atlas-memory.local",
            "user_id": "service:mcp",
            "tenant_id": "orion",
            "namespace": "ops",
            "top_k": 2,
            "enabled": True,
        }
    )

    def fake_search(query):
        assert query == "route status"
        return {
            "hits": [
                {
                    "content": "Cosmocrat public health route is served by Edge.",
                    "namespace": "ops",
                    "similarity": 0.91,
                }
            ]
        }

    monkeypatch.setattr(provider, "_search", fake_search)

    context = provider.prefetch("route status")

    assert "Atlas Estate Recall" in context
    assert "[ops sim=0.910]" in context
    assert "Cosmocrat public health route" in context


def test_atlas_estate_prefetch_fails_closed(monkeypatch):
    provider = AtlasEstateMemoryProvider(
        {
            "base_url": "http://atlas-memory.local",
            "user_id": "service:mcp",
            "tenant_id": "orion",
            "namespace": "ops",
            "enabled": True,
        }
    )

    def failing_search(query):
        raise RuntimeError("network down")

    monkeypatch.setattr(provider, "_search", failing_search)

    assert provider.prefetch("route status") == ""


def test_atlas_estate_provider_can_be_disabled():
    provider = AtlasEstateMemoryProvider({"enabled": False})

    assert provider.is_available() is False
    assert provider.prefetch("anything") == ""
