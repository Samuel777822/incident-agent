# Runtime monitoring adapters

Agent Daemon has two complementary signals:

- **Push checks** verify the repository when code is pushed: install, build, type-check, tests, and startup checks in the isolated sandbox.
- **Runtime monitoring** reports failures observed while the deployed application is running.

When a project is connected in runtime or both-watch mode, Agent Daemon inspects the Git tree and generates an installation pull request for the detected stacks. Mixed repositories can receive more than one adapter.

## Supported runtime adapters

| Stack | Automatic installation | Captures |
| --- | --- | --- |
| Python | Adds `incident_agent_monitor.py` and imports it from a recognised entry file | Uncaught main-thread and thread exceptions; ERROR-level logging |
| Node.js (CommonJS / ESM) | Adds the matching `.cjs` or `.mjs` monitor and imports it from a recognised server entry file | Uncaught exceptions; failed fetch responses (5xx/429 and 4xx from recognised AI-provider hosts) |
| Browser JavaScript / TypeScript | Adds a browser monitor and injects it into a recognised HTML entry file | Uncaught errors, unhandled promise rejections, resource load failures, and API responses 5xx/429 |
| Java 11+ | Adds a standard-library helper beside the detected main class and calls it from `main` | Uncaught exceptions and `java.util.logging` SEVERE records with stack traces |
| Static HTML | Injects the browser monitor script into an HTML entry file | Browser-side failures observable by the script |

The installer deliberately avoids rewriting application architecture or adding third-party packages. It patches only entrypoints it can identify with a conservative rule. The generated `INCIDENT_AGENT_SETUP.md` explains exactly what was added and which files were instrumented.

## Credentials and deployment

The application creates two project-scoped credentials:

1. The **server ingest key** authenticates private server-side reporters. It is written into `incident_agent_config.json` only when the customer's GitHub repository is private.
2. The **browser reporting token** can only submit error events for one project. It cannot read project data, change settings, pause a project, or trigger fixes. It is rate-limited and origin-checked when the customer provided an app URL. This restricted token is safe to include in frontend assets and is also the fallback reporter for public repositories.

The browser token is derived from the project server key. Rotating the server key also invalidates the prior browser token. Agent Daemon stores only the browser token hash in its database; no additional customer environment variable is required.

Private repositories receive both credentials in the generated config. Public repositories receive only the restricted browser token; the powerful server key is never committed to public source. The monitoring clients read config from the repository at runtime and can also use server environment variables as an override.

## Data minimisation

Adapters send timestamps, severity, service name, a short error message, exception type, and stack trace. They do not intentionally send page contents, form values, request bodies, user records, or full network responses. Browser resource URLs are reduced to origin and path before reporting. Basic bearer and common OpenRouter/OpenAI key patterns are redacted before sending.

## Coverage boundaries

Monitoring catches failures that the runtime exposes. It cannot infer every broken user experience:

- A handled error that is neither thrown nor logged may be invisible to a generic runtime hook.
- A logically incorrect response that still returns HTTP 200 needs a test or explicit application instrumentation.
- Browser reporting requires the application to allow outbound requests to the Agent Daemon ingest endpoint in its Content Security Policy.
- Automatic entrypoint detection is conservative. If the repository uses a custom startup command or framework layout that is not recognised, the PR includes the monitor files and setup notes but may not insert the startup hook.

These limits are why runtime monitoring is paired with push-time build and test checks. Agent Daemon should never claim that an unobserved bug class is covered.
