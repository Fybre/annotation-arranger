# Annotation Arranger

A synchronous REST service for Therefore PDFs. It retrieves a document using the supplied
token, arranges stamp annotations and/or flattens all annotations, replaces only changed PDF streams, verifies
the persisted content, and then returns success. No polling or Docker is required.

Python 3.12+ with FastAPI, pypdf, pikepdf/qpdf, and httpx. Runs on Linux, macOS, and Windows.

## Standalone executables and GitHub releases

Release archives contain a **single executable** with Python and the PDF libraries bundled,
plus service configuration, setup instructions, dependency notices and build metadata.
The destination machine does not need Python or Docker. Windows packages also include a
checksum-verified WinSW wrapper for background service installation.

GitHub Actions builds and tests natively on these runners:

| Asset | Runner |
|---|---|
| Windows x64 | Windows Server 2022 |
| Linux x64 | Ubuntu 22.04 |
| Linux ARM64 | Ubuntu 22.04 ARM |
| macOS Intel | macOS 15 Intel |
| macOS Apple Silicon | macOS 15 ARM |

Every build runs the unit tests, packages with PyInstaller, and exercises the frozen
executable outside the checkout: PDF alignment/flattening, TLS certificate loading,
HTTP startup, API schema, and request validation. Linux also runs PDF render comparisons.
The release is published only after all five targets succeed and all archive checksums
have been verified. Executables are unsigned; older operating systems and Alpine/musl
Linux are not verified. The public HTTPS endpoint/tunnel is configured separately.

To build locally for the current OS/CPU:

```sh
uv sync --locked --group build
uv run python scripts/build_release.py
```

Archives and checksums appear under `dist/releases/`. The release workflow can also be
started manually from GitHub Actions to obtain build artifacts without publishing.

To publish a release, update the version in `pyproject.toml`, commit and push `main`, then:

```sh
uv run python scripts/release.py --dry-run
uv run python scripts/release.py
```

This creates/pushes the matching `v<version>` tag. GitHub builds the five archives, creates
a draft release, uploads all assets plus `SHA256SUMS.txt`, then publishes it. GitHub's
automatic token is sufficient; no Therefore credentials or separate release token are
required. Workflow actions are pinned to commits. Standard GitHub-hosted runners can build the public repository without Docker.

Uploaded invoices, live tenant snapshots, backups, tokens, temporary tunnel state and
local build outputs are excluded from Git. Tests use a generated synthetic PDF under
`tests/fixtures/`, created by `arranger.self_test.synthetic_pdf()`.

## Run locally

With [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked
uv run python -m arranger
```

Or create a virtual environment with Python and install the project dependencies:

```sh
python -m venv .venv
# macOS/Linux:
.venv/bin/python -m pip install .
.venv/bin/python -m arranger
# Windows:
.venv\Scripts\python.exe -m pip install .
.venv\Scripts\python.exe -m arranger
```

Default address: `http://127.0.0.1:8765`. Interactive request documentation: `/docs`.
Health endpoint: `GET /health` (process health, not a Therefore connection test).
Use one server worker; in-process locks reject concurrent work on the same document.
Server-side checkout and the version/timestamp checks also protect remote edits.

The default configuration permits only category **392** on **craigdemo**. Environment
variables are listed in `.env.example`; set them in the shell or service configuration.
The application does not automatically read `.env` files.

## POST contract

`POST /arrange-annotations`, with `Content-Type: application/json`:

```json
{
  "docNo": 28729,
  "token": "YOUR_THEREFORE_JWT",
  "alignment": "auto",
  "flatten": false,
  "dryRun": false,
  "gap": 6,
  "margin": 12
}
```

Only `docNo` and `token` are required. `gap` and `margin` are PDF points (72 points =
one inch). `dryRun: true` returns proposed moves without checkout, backup, or save.

`alignment` is optional. It defaults to `auto` for an ordinary arrangement request.
With `flatten: true`, omitting `alignment` means **flatten only**, without moving stamps:

| Value | Placement on each visible page |
|---|---|
| `left` | A vertical column at the left margin, starting at the top |
| `right` | A vertical column at the right margin, starting at the top |
| `top` | A horizontal row at the top margin, starting at the left |
| `bottom` | A horizontal row at the bottom margin, starting at the left |
| `auto` | Keep separated stamps where they are; move overlapping stamps to the closest available position |

Edge layouts preserve annotation order and stamp sizes. They arrange all stamps, including
a single stamp. `margin` controls the inset from the page edge and `gap` the spacing.
If the row or column does not fit, the request fails without saving. Page rotation is
accounted for so `top` means the top as displayed in the viewer. Invalid alignment
values return HTTP 422. The response includes the selected `alignment`.

### Flatten alone or after alignment

To flatten without rearranging:

```json
{"docNo": 28729, "token": "YOUR_THEREFORE_JWT", "flatten": true}
```

To arrange first, then flatten:

```json
{
  "docNo": 28729,
  "token": "YOUR_THEREFORE_JWT",
  "alignment": "bottom",
  "flatten": true
}
```

`flatten` is an optional JSON boolean, default `false`. Flattening burns saved visible
annotation appearances into vector page content and removes all page annotation objects,
including non-stamp marks, links, popups and form widgets. Form values become static text;
link actions, popup interaction and form editing are removed. Hidden/invisible marks are
removed without making them visible. Popup comment text is not appended as a new page.
This is visual flattening, not rasterization or application of redactions.

Every page is processed, even pages with no stamps. The service verifies there are no
remaining page annotations before saving. `annotationsFlattened` reports the number of
annotation objects processed, including nonvisual links/popups, both in the overall
response and per stream. `annotationsMoved` reports only stamp moves before flattening.
`alignment` is `null` for flatten-only requests. `dryRun: true` validates the full operation
and reports planned counts without saving. An already flattened document returns
`unchanged` without creating another version.

Visible annotations must have valid saved appearance streams; supported form fields can
have appearances generated by qpdf. If a visible mark has no usable appearance, the service
returns an error rather than silently discarding it. Resave that PDF in its viewer first.
Unsupported XFA forms and signed/certified/encrypted PDFs are rejected. Flattened stamps
can no longer be realigned as annotations; original PDFs remain in the backup and Therefore
version history. This behavior uses [pikepdf annotation flattening](https://pikepdf.readthedocs.io/en/stable/api/main.html#pikepdf.Pdf.flatten_annotations).

Successful response (HTTP 200, after verification):

```json
{
  "docNo": 28729,
  "status": "updated",
  "version": 4,
  "annotationsMoved": 1,
  "annotationsFlattened": 0,
  "streams": [],
  "elapsedMs": 1447
}
```

Actual `streams` entries contain the file name, stream number, stamp count, and each
move's page, annotation identifier, and before/after rectangles.
Status is `updated`, `unchanged`, or `dry_run`. An unchanged document is not saved again.

Errors use non-2xx HTTP status with `status`, `code`, and `message`: 403 for token/permission
or category restrictions, 409 for checkout/conflicting edits, 413 for oversized PDFs, 422
for unsupported/invalid PDFs, and 502/504 for Therefore errors/timeouts. Do not configure
the workflow to treat every HTTP response as success. An ambiguous save returns
`save_outcome_unknown`: inspect the document before retrying. No automatic write retries
or undo-checkout are attempted after a save starts, to avoid discarding an uncertain save.

The default processing budget is 120 seconds, checked before each Therefore call; individual
network operations have a maximum 45-second timeout. This is not a hard cancellation
guarantee for PDF parsing or a slow network response. Configure the workflow and any proxy
with a longer request timeout (for example 150 seconds). A caller disconnect cannot reliably
cancel a save already in progress. Small files are expected; total PDF input is capped at
20 MB and each PDF at 200 pages after retrieval.

## Authentication

The normal request accepts a JWT bearer token, including a workflow-generated JWT once
validated. No username/password is stored in the server configuration.

For manual testing, obtain a JWT interactively:

```sh
uv run python scripts/get_token.py --username craig.mewett --output /tmp/arranger-token.txt
```

The password is prompted without echo. The token is written to a new private file, not
printed; remove it when finished. On Windows, choose a private path and apply appropriate
file permissions. Never commit tokens, passwords, request bodies, or private document backups.

`GetConnectionToken` is a different token type: it requires Basic authentication with
username/token and `UseToken: 1`, not bearer authentication. To supply that type, include
`"username": "craig.mewett"` along with `token` in the POST body. This legacy mode is
implemented and authentication was verified live; the document save tests used a JWT
obtained through `GetJWTToken`.

The Therefore URL and tenant are configured on the server, never accepted from a request.
Requests and tokens are not logged. Validation errors do not echo request inputs.
Keep the listener local or behind an HTTPS reverse proxy with controlled ingress before
making it accessible from a remote workflow. Set `HOST=0.0.0.0` only when direct network
access is intended and transport security is provided. A Therefore Online workflow cannot
reach this computer's loopback address.

## Arrangement rules and limits

- Process PDF streams only. Leave other attachments alone.
- In `auto` mode, preserve the first stamp's position and dimensions. Process later
  stamps in annotation order and choose the closest available position relative to
  already placed stamps, using movement distance in page coordinates. This may move a
  stamp up, down, left, or right. Equal-distance ties prefer downward movement. This is
  a greedy arrangement, not a global optimization of all stamps together. New positions
  respect `margin`; existing separated stamps are left alone, including near an edge.
- Edge alignment modes move all stamps into one row or column at the selected edge.
  No resizing, wrapping, or page creation is performed. If no position fits, fail
  without saving.
- Without flattening, preserve stamp appearance streams, identifiers, author/date metadata, page content,
  and annotation status. An associated popup moves with its parent stamp.
- Without flattening, leave unrelated annotations such as links and highlights in place.
- Handle quarter-turn page rotations and custom page units.
- Reject signed/certified/encrypted PDFs, malformed stamps, protected stamps that need
  moving, out-of-page stamps, and unsupported separate annotation streams.
- Flattened stamps cannot be moved by this service. For arrangement alone, no PDF stamp
  annotations means a successful unchanged result with zero stamps. Flattening also
  processes other annotation types when no stamps exist. No PDF streams is an error.
- This version prevents **stamp-to-stamp** overlap; it does not identify blank areas or
  avoid underlying text/images. The original anchor may already cover document content.
- Back up changed source PDFs under `var/backups/<docNo>/<version>/` before saving.
  Backups include a stream-name/hash manifest; protect and retain this directory as needed.

## Save behavior

1. Read category, index metadata, streams and checkout status.
2. Arrange and/or flatten and validate all PDF streams locally before any remote write.
3. Persist backups of originals that need changes.
4. Check out the document; reject an existing checkout, including one held by the caller.
5. Recheck its version and change timestamp.
6. Call `UpdateDocument` with only changed stream numbers and an empty index-data update
   carrying `LastChangeTimeISO8601` (existing index values are retained).
7. Retrieve the saved PDFs, compare their exact bytes and ensure checkout was released.
8. Return success with the new version number.

Live testing confirmed that `UpdateDocument` saved and released this checkout itself;
an additional `CheckInDocument` was not needed. The same document number is retained,
and Therefore creates a new version, preserving its history.

## Running as a service

Example templates are in `deploy/`. Adjust paths, service user, host, tenant, category
allowlist, and private writable backup/log directories before installing. Create the
virtual environment on each host; do not copy a `.venv` across operating systems.

- **Linux:** create the `annotation-arranger` service account, install under
  `/opt/annotation-arranger`, copy the unit to `/etc/systemd/system/`, then run
  `systemctl daemon-reload` and `systemctl enable --now annotation-arranger` as administrator.
- **macOS:** create/configure the service account and directories, adjust the plist,
  install it in `/Library/LaunchDaemons/` with root ownership and mode 644, then run
  `sudo launchctl bootstrap system /Library/LaunchDaemons/com.annotation-arranger.plist`.
- **Windows:** install under `C:\annotation-arranger`, create the virtual environment,
  place a compatible [WinSW](https://github.com/winsw/winsw) executable named
  `annotation-arranger.exe` beside the supplied `annotation-arranger.xml`, and run
  `annotation-arranger.exe install` followed by `annotation-arranger.exe start` from an
  administrator terminal. Configure the service identity and directory permissions.

These templates are supplied for deployment; no system service has been installed by
the development tests. Use one instance per tenant until distributed locking is added.

## Verification

```sh
uv run pytest -q
uv run ruff check arranger scripts tests
uv run ruff format --check arranger scripts tests
```

Live tests on 3 November 2026, craigdemo / Stamp Test (category 392):

| Document | Result | Duration | Repeat request |
|---|---|---|---|
| 28729 — test1 | One stamp moved, version 3 → 4 | 1.447 s | Unchanged, version 4 |
| 28732 — test2 | One stamp moved, version 3 → 4 | 2.179 s | Unchanged, version 4 |

Subsequent live flatten tests on the same date:

| Document | Operation | Result | Duration |
|---|---|---|---|
| 28729 — test1 | Flatten only | 2 annotations flattened, no moves, version 4 → 5 | 1.349 s |
| 28732 — test2 | Bottom alignment + flatten | 2 stamps moved and flattened, version 4 → 5 | 1.747 s |

Both saved version-5 PDFs were re-retrieved and confirmed to have no remaining page
annotations, unchanged index values, and released checkouts. Repeated requests returned
unchanged without a new version. Snapshots and responses are in `output/live-flatten-test/`.
The automated suite also covers mixed annotation types, text form values, checkbox states,
rotated/cropped pages, dry runs and no-op retries. When Poppler is installed, render comparison
tests verify page appearance before and after flattening.

Both requests were sent over HTTP to the running service with a JWT, and saved bytes
were retrieved from Therefore before returning HTTP 200. Original snapshots, previews,
and responses are in ignored `output/live-test/`; protected originals are in `var/backups/`.
Workflow-generated token handling and the workflow's outbound timeout still need a live test.

API references: [GetJWTToken](https://therefore.net/help/Online/en-us/AR/SDK/WebAPI/the_webapi_operation_getjwttoken.html),
[connection tokens](https://therefore.net/help/2026/en-us/AR/SDK/WebAPI/the_webapi_securitytokens.html),
[UpdateDocument](https://therefore.net/help/Online/en-us/AR/SDK/WebAPI/the_webapi_operation_updatedocument.html).
