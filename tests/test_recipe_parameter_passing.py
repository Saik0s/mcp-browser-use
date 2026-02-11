from mcp_server_browser_use.recipes.analyzer import _apply_public_parameter_allowlist
from mcp_server_browser_use.recipes.models import Recipe, RecipeParameter


def test_apply_public_parameter_allowlist_inlines_defaults_and_drops_params() -> None:
    url = "https://example.com/api/search?q={query}&session={session}&limit={limit}&tracking={tracking}"
    body_template = '{"q":"{query}","nonce":"{nonce}","keep":"x"}'
    parameters = [
        RecipeParameter(name="query", required=True, default=None),
        RecipeParameter(name="limit", required=False, default="10"),
        RecipeParameter(name="session", required=False, default="s123"),
        RecipeParameter(name="tracking", required=False, default="t1"),
        RecipeParameter(name="nonce", required=False, default="n0"),
    ]

    new_url, new_body, kept = _apply_public_parameter_allowlist(url, body_template, parameters)

    assert "q={query}" in new_url
    assert "limit={limit}" in new_url
    assert "{session}" not in new_url
    assert "{tracking}" not in new_url
    assert "session=s123" in new_url
    assert "tracking=t1" in new_url

    assert new_body is not None
    assert '"nonce":"n0"' in new_body
    assert "{nonce}" not in new_body

    kept_names = {p.name for p in kept}
    assert kept_names == {"query", "limit"}


def test_merge_params_maps_query_alias_to_q_and_limit_to_per_page() -> None:
    recipe = Recipe(
        name="test",
        description="test",
        original_task="test",
        parameters=[
            RecipeParameter(name="q", required=True),
            RecipeParameter(name="per_page", required=False, default="20"),
        ],
    )

    merged = recipe.merge_params({"query": "dogs", "limit": 5})
    assert merged["q"] == "dogs"
    assert merged["per_page"] == 5
