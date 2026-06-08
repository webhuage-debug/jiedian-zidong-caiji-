# Subscription Region Filter Update

Date: 2026-06-08

## Scope

- Added default publish-region filtering for subscription pool generation.
- Default publishable regions are Asia first, then US.
- Europe, Africa, and unknown regions remain in the database but are excluded from the default subscription pool.
- No Docker, deployment, Telegram Bot flow, data, logs, or environment files were changed.

## Rules

- Asia allowlist: JP, SG, HK, TW, KR, MY, TH, VN, PH.
- US allowlist: US.
- Excluded examples: GB/UK, DE, FR, NL, RU, TR, ZA, EG, NG, KE, MA, and unknown.
- Region detection uses existing country values first, then node URI text such as remarks, fragments, hostnames, and VMess metadata.

## Tests

- `python -m py_compile node_region.py node_database.py web_app.py`
- `python -m unittest test_node_region.py test_node_database.NodeDatabaseTest.test_subscription_pool_defaults_to_asia_then_us_and_excludes_other_regions test_node_database.NodeDatabaseTest.test_subscription_export_uses_premium_pool_top_twenty test_web_app.WebAppRoutingTest.test_public_subscription_get_outputs_client_content_directly -v`
- `python -m unittest discover -v`

All tests passed locally with the bundled Codex Python runtime.
