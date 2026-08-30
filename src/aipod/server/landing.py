"""The HTML page served at ``/`` when running over Streamable HTTP."""

from __future__ import annotations

from ..branding import LOGO_SVG

_LANDING_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>aipod</title>
<style>
  :root { color-scheme: light dark; }
  body {
    margin: 0; padding: 3rem 1.25rem 5rem;
    font: 16px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    background: #0b0d12; color: #e7e9ee;
  }
  main { max-width: 820px; margin: 0 auto; }
  h1 { font-size: 1.9rem; margin: 0 0 .25rem; }
  .tag { color: #8b93a7; margin: 0 0 2rem; }
  code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .endpoint {
    display: inline-block; background: #151922; border: 1px solid #262c3a;
    border-radius: 8px; padding: .55rem .8rem; margin: .2rem .4rem .2rem 0;
    text-decoration: none; color: #e7e9ee;
  }
  a.endpoint:hover { border-color: #3d64a8; }
  .endpoint .muted { color: #6b7385; font-size: .82rem; }
  h2 { font-size: 1.05rem; margin: 2.2rem 0 .6rem; color: #c8cede; }
  ul { margin: 0; padding-left: 1.2rem; }
  li { margin: .2rem 0; }
  li b { color: #9ecbff; font-weight: 600; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1.5rem; }
  a { color: #9ecbff; }
  footer { margin-top: 3rem; color: #6b7385; font-size: .9rem; }
  .brand { display: flex; align-items: center; gap: .7rem; margin-bottom: .25rem; }
  .brand svg { flex: none; }
  .brand h1 { margin: 0; }
</style>
</head>
<body>
<main>
  <div class="brand">__LOGO__<h1>aipod &mdash; server mode</h1></div>
  <p class="tag">A reference Model Context Protocol server that exercises every MCP feature &mdash; built with
  <a href="https://ai.pydantic.dev">pydantic-ai</a>.</p>

  <h2>Endpoints</h2>
  <div>
    <span class="endpoint"><code>POST&nbsp;/mcp</code> &mdash; MCP (Streamable HTTP)</span>
    <a class="endpoint" href="/health"><code>GET&nbsp;/health</code></a>
    <a class="endpoint" href="/contract.json"><code>GET&nbsp;/contract.json</code> &mdash; service contract</a>
    <a class="endpoint" href="/.well-known/oauth-protected-resource"><code>GET&nbsp;/.well-known/oauth-protected-resource</code>
      <span class="muted">&mdash; when auth is enabled</span></a>
    <a class="endpoint" href="/metrics"><code>GET&nbsp;/metrics</code>
      <span class="muted">&mdash; Prometheus, when metrics are enabled</span></a>
  </div>
  <p class="tag">The companion <code>aipod agent</code> publishes an agent card at
  <code>/.well-known/agent-card.json</code> (A2A shape, with a link back to this
  contract).</p>

  <div class="grid">
    <div>
      <h2>Protocol tools</h2>
      <ul>
        <li><b>echo</b> &mdash; echo the input</li>
        <li><b>add</b> &mdash; add two numbers</li>
        <li><b>get_tiny_image</b> &mdash; text + image blocks</li>
        <li><b>get_annotated_message</b> &mdash; priority / audience annotations</li>
        <li><b>get_structured_weather</b> &mdash; typed output schema</li>
        <li><b>get_resource_reference</b> &mdash; embedded resource block</li>
        <li><b>get_resource_links</b> &mdash; resource_link blocks</li>
        <li><b>trigger_long_running_operation</b> &mdash; progress updates</li>
        <li><b>toggle_simulated_logging</b> &mdash; periodic log messages</li>
        <li><b>toggle_subscriber_updates</b> &mdash; resources/updated events</li>
        <li><b>poet</b> / <b>summarize</b> / <b>weather_report</b> &mdash; pydantic-ai via MCP sampling</li>
      </ul>
      <h2>Marvel roster</h2>
      <ul>
        <li><b>list_heroes</b> / <b>get_hero</b> &mdash; typed roster output</li>
        <li><b>find_heroes_by_power</b> &mdash; search by power</li>
        <li><b>assemble_team</b> &mdash; pick heroes for a threat</li>
        <li><b>hero_bio</b> &mdash; pydantic-ai bio via sampling</li>
      </ul>
    </div>
    <div>
      <h2>SRE / IT-application</h2>
      <ul>
        <li><b>list_services</b> / <b>get_service</b> &mdash; service catalogue</li>
        <li><b>check_service_health</b> &mdash; metrics + SLO + incidents &rarr; verdict</li>
        <li><b>error_budget</b> &mdash; SLO budget + burn rate</li>
        <li><b>search_logs</b> &mdash; deterministic synthetic log search</li>
        <li><b>list_incidents</b> / <b>open_incident</b> / <b>update_incident</b></li>
        <li><b>list_deployments</b> / <b>rollback_deployment</b></li>
        <li><b>get_oncall</b> &mdash; on-call + escalation</li>
        <li><b>get_runbook</b> &mdash; runbook steps by symptom</li>
        <li><b>incident_postmortem</b> &mdash; pydantic-ai draft via sampling</li>
      </ul>
    </div>
    <div>
      <h2>Resources</h2>
      <ul>
        <li><code>demo://resource/dynamic/text/{resource_id}</code></li>
        <li><code>demo://resource/dynamic/blob/{resource_id}</code></li>
        <li><code>hero://roster/{codename}</code></li>
        <li><code>service://catalog/{name}</code></li>
        <li><code>runbook://{service}</code></li>
        <li><code>demo://resource/static/instructions.md</code></li>
        <li><code>demo://resource/static/features.md</code></li>
      </ul>
      <h2>Prompts</h2>
      <ul>
        <li><b>simple_prompt</b></li>
        <li><b>args_prompt</b> (city, state?)</li>
        <li><b>completable_prompt</b> (department &rarr; name)</li>
        <li><b>resource_prompt</b> (embeds a resource)</li>
      </ul>
      <h2>Also</h2>
      <ul>
        <li>Argument completion</li>
        <li>Resource subscriptions</li>
        <li>Client-controlled logging level</li>
        <li>Optional bearer auth (OAuth 2.1 protected resource)</li>
        <li>Optional OpenTelemetry metrics (<code>/metrics</code>)</li>
      </ul>
    </div>
  </div>

  <footer>
    Connect with any MCP client, e.g.
    <code>npx @modelcontextprotocol/inspector</code>, then point it at
    <code>http://&lt;host&gt;:&lt;port&gt;/mcp</code>.
  </footer>
</main>
</body>
</html>
"""

LANDING_HTML = _LANDING_HTML.replace("__LOGO__", LOGO_SVG)
