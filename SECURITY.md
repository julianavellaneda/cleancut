# Security

## What is by design, and not a vulnerability

CleanCut is a local-first tool. **Every route except the three destructive admin wipes is
unauthenticated**, and that is deliberate: the interface the port sits on *is* the access control.
`CLEANCUT_HOST` defaults to `127.0.0.1`, so a default installation is reachable from the machine it
runs on and nowhere else.

So the following are documented behaviour rather than bugs, and reports of them will be closed as
such:

- The jobs list, the original recording, the stored transcript, the waveform and the export are
  readable by anything that can reach the port.
- `GET /api/admin/stats` is ungated — the dashboard has to load on a server nobody has configured
  yet.
- There is no per-user auth, no sessions and no ownership model. CleanCut assumes one operator.

See the README's [Privacy](README.md#privacy) section, and the "Network binding" and "Admin auth"
notes in [`CLAUDE.md`](CLAUDE.md), for the reasoning in full.

## If you are deploying past localhost

Two settings decide whether that is safe:

- **`CLEANCUT_HOST`** — anything but a loopback address opens every route above to the network.
  The backend warns at startup but does not refuse. Put a reverse proxy that authenticates in
  front of it before you do this.
- **`ADMIN_TOKEN`** — the shared secret for `reset-database`, `clear-storage` and `reset-all`, sent
  as `X-Admin-Token`. Unset, those three routes answer **503**: they fail closed, because an unset
  variable is the state every deployment starts in and the last one that should hand out a delete
  button. `ALLOW_UNAUTHENTICATED_ADMIN=1` reopens them for local use, and is ignored both when
  `ADMIN_TOKEN` is set and once `CLEANCUT_HOST` is not loopback.

One known limitation worth naming rather than discovering: `MAX_UPLOAD_MB` bounds what CleanCut
*keeps*, not what a client can make it receive. Starlette spools the multipart body to a temp file
before any application code runs, so a 50 GB POST costs 50 GB of scratch disk on its way to a 413.
That cannot be fixed in the handler. Cap the request body at the proxy on any non-loopback
deployment.

## Reporting a vulnerability

For anything outside the above — a path traversal in the media routes, a way past the admin gate,
an injection through a prompt or a preset, a dependency advisory that actually reaches this code —
please report it privately rather than in a public issue.

Use GitHub's private vulnerability reporting: the **Security** tab on this repository, then
**Report a vulnerability**. That opens a private advisory thread visible only to the maintainers.

Please include what you were able to do, the steps to reproduce it, and whether you were running
the Docker or the local quickstart. A proof of concept helps; a working exploit against someone
else's instance is not welcome.

There is no bounty. Expect a first reply within a week — this is a personal project, not a staffed
one, and a slow acknowledgement is not an invitation to disclose publicly.

## Supported versions

The latest release and `main`. Older tags are not patched.
