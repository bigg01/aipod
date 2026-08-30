# Why I built a fake MCP server on purpose

*Notes from a Solution Architect for AI, coming out of SRE and platform
engineering, on testing agentic infrastructure — and why `aipod` exists.*

---

## The job, and the gap in it

Part of my job is building the plumbing that other people's agents and tools
run on: gateways, routers, registries, policy engines, the CI pipelines that
decide whether an MCP server is safe to ship. None of that plumbing is
interesting on its own — it only earns its keep against something real flowing
through it.

And that's where things get awkward. "Something real" usually means one of
three options, and I've tried all three long enough to be tired of each:

- **Test against production.** Slow, shared, and the last thing you want is a
  gateway experiment touching a service someone else depends on.
- **Hand-roll a stub.** Fast to start, and it rots immediately — it implements
  the three tool calls you personally needed last Tuesday and nothing else. It
  can't tell you whether your gateway handles a resource template, a
  completion request, or a sampling round-trip, because it doesn't have any.
- **Wait for a "real" MCP server from another team.** Now your platform work
  is blocked on someone else's roadmap, and when it does arrive it usually
  only exercises the slice of the protocol that team happened to need.

What none of these give you is a server that is *deliberately* exhaustive —
one built with the explicit goal of exercising every corner of MCP, not just
the corner one product needed. So I built one.

## What `aipod` actually is

`aipod` is one binary with two modes, chosen by a subcommand:

- **`aipod server`** — a reference MCP server. Its job is not to be useful in
  the business sense; its job is to implement *every* MCP feature correctly,
  in one place, behind one endpoint: tools with structured output, static and
  templated resources, prompts with argument completion, resource
  subscriptions, progress notifications, logging levels, and MCP sampling
  (tools that borrow the *caller's* model instead of holding a key of their
  own).
- **`aipod agent`** — a small [pydantic-ai](https://ai.pydantic.dev) agent
  that connects to an `aipod server` over MCP and hands its tools to a real
  model. It exists so you have something to point at the server that behaves
  like an actual consumer, not just a protocol prober.

To make the tool calls feel like something rather than `foo`/`bar`/`baz`, the
server carries two toy domains: a Marvel hero roster (`list_heroes`,
`get_hero`, `assemble_team`, typed `Hero` output) and a small SRE / IT
estate — services, incidents, deployments, on-call, runbooks — with genuine
mutable state (`open_incident`, `rollback_deployment`) and deterministic
synthetic logs and metrics. Neither is the point. They're there so that when
you're testing a gateway's handling of `sideEffects: true`, or a policy
engine's handling of `dataEgress`, you're testing it against a tool call that
*reads* like a real one — not an abstraction so thin it hides the bugs that
only show up with realistic payload shapes.

The whole thing packages into a ~34 MB `FROM scratch` container, runs the same
image in either mode, and ships Kubernetes manifests for both. That matters
more than it sounds: a test fixture you have to hand-configure every time
stops being a fixture.

## What it's for, concretely

**Gateway and router conformance.** If you're writing something that sits in
front of MCP servers — auth, rate limiting, routing, schema validation — it
needs to survive contact with every feature a *compliant* server might throw
at it, not just the tool-call happy path. `aipod server` gives you resource
templates, prompt completion, subscriptions, and progress streams to point
your gateway at before a real integration finds the gap for you.

**A CI gate that isn't a leap of faith.** `uv run pytest` drives the server
through an in-memory MCP session with a stubbed sampling callback — no
listener, no model key, fully hermetic. That's the test suite I lift almost
verbatim as the starting template whenever a team asks "how do I even write
tests for an MCP server." Layer the
[MCP Inspector](https://github.com/modelcontextprotocol/inspector) `--cli` on
top and you get scripted, `jq`-able assertions against a live protocol
session — good for a build step that fails when a tool silently disappears
or a schema quietly narrows.

**Auth and OAuth 2.1, without standing up an identity provider.** Start the
server with a key and `/mcp` becomes an OAuth 2.1 protected resource: bearer
tokens, RFC 9728 metadata at `/.well-known/oauth-protected-resource`, scopes.
That's enough surface to validate a client's or gateway's auth handling —
"does it discover the auth server from the 401 challenge, does it hold onto a
token correctly" — before it ever talks to production identity
infrastructure.

**Sampling, the feature everyone forgets to test.** `poet`, `summarize`, and
`weather_report` don't carry API keys — they ask the *client* to run a model
via `sampling/createMessage`. That inversion is exactly the kind of thing that
looks fine in a design doc and breaks the first time a real client tries it.
`aipod` gives you both ends of that handshake to test against: the Inspector's
Sampling tab to answer requests by hand, or `aipod agent` to drive it
end-to-end with a real model.

**Contracts and agent cards as artifacts, not documentation.** `aipod server`
publishes a full service contract (`GET /contract.json`) generated by
introspecting its own running tools, resources, and prompts. `aipod agent`
publishes an agent card (`GET /.well-known/agent-card.json`) in the
Agent2Agent shape, governance labels included. If you're building a registry,
a policy engine, or an SDK generator, these are two known-good, always-in-sync
example documents to develop against — instead of guessing at the shape from
a spec and finding out you guessed wrong when a real server disagrees.

## The point, stated plainly

Platform work lives or dies on whether the thing underneath it is trustworthy
enough to build on. A fixture that only covers the features one team happened
to use isn't infrastructure — it's a liability wearing infrastructure's
clothes, because everyone who tests against it inherits its blind spots. The
value of `aipod` isn't the poet tool or the Marvel roster; it's that it
refuses to be partial. Every gateway, every router, every CI check that's
been run against it has been run against the full protocol, not a convenient
subset of it — which means the gaps that turn up in production are gaps
nobody's fixture papered over, because this one didn't have any to paper over
in the first place.

If you're building anything that sits between an MCP client and an MCP
server — or anything that has to *decide* things about an agent based on its
card or its contract — point it at `aipod` before you point it at anything
real. See [`docs/testing-mcp.md`](../testing-mcp.md) for the full walkthrough,
tool by tool.
