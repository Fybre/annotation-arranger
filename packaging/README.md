# Annotation Arranger executable

This archive includes a standalone executable with Python and the required PDF libraries.
No Python installation or Docker is needed on the destination machine.

## Run

```sh
./annotation-arranger --help
./annotation-arranger --self-test
./annotation-arranger --host 127.0.0.1 --port 8765
```

On Windows use `.\annotation-arranger.exe` instead of `./annotation-arranger`.
Before starting normally, rename `settings.example.env` to `.env` beside the executable
and replace the server/tenant placeholders. The executable reads that file automatically,
even when launched as a service from another working directory. No Python or shell dotenv
command is needed. For another location use `--env-file /path/to/settings.env`.

```dotenv
THEREFORE_BASE_URL=https://your-tenant.thereforeonline.com/theservice/v0001/restun
THEREFORE_TENANT=your-tenant
HOST=127.0.0.1
PORT=8765
BACKUP_ENABLED=false
BACKUP_DIR=var/backups
```

CLI options override existing process environment variables, which override `.env`.
Restart after editing. There is no built-in server/tenant; without a configured URL,
normal startup fails clearly. All categories accessible with the supplied token are
supported. No credentials are stored in the executable.

Local backups are off by default. Enable with `BACKUP_ENABLED=true` or `--backup`;
choose a private writable `BACKUP_DIR` (or `--backup-dir`). Relative paths resolve beside
`.env`; setting a directory alone does not enable backups. Use `--no-backup` to override
an enabled setting. Therefore version history remains independent of local backups.

`GET /health` reports process health. `GET /docs` opens the API documentation.
`POST /arrange-annotations` accepts JSON:

```json
{"docNo": 12345, "token": "YOUR_JWT", "alignment": "bottom", "flatten": false, "dryRun": true}
```

Omit `alignment` with `flatten: true` to flatten alone. Set `dryRun: false` to save.
Without flattening or explicit alignment, alignment defaults to auto. The response is
returned after saving and verifying, with a success/error status. Original PDFs are backed
up before replacement only when local backups are enabled. Flattened annotations become static page content and cannot be
realigned later; unsupported appearances fail without saving.

## Background service

**Windows:** retain the whole extracted folder. From an administrator PowerShell:

```powershell
New-Item -ItemType Directory -Force var
cd service
.\annotation-arranger-service.exe install
.\annotation-arranger-service.exe start
```

The XML uses paths relative to its own location. Use Windows Services to configure a
suitable service account and grant it access to the application and backup/log directories.
To stop/remove: `annotation-arranger-service.exe stop` and `annotation-arranger-service.exe uninstall`.

**Linux:** copy the extracted folder to `/opt/annotation-arranger`, create an
`annotation-arranger` system account, and ensure it can execute the binary. Configure the adjacent `.env` before starting. If local backups are enabled, use a
backup directory writable by the service account, such as `/var/lib/annotation-arranger/backups`:

```sh
sudo cp service/annotation-arranger.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now annotation-arranger
```

**macOS:** copy the extracted folder to `/opt/annotation-arranger`. Edit
`service/com.annotation-arranger.plist` so `UserName` names the account that should run it;
give that account write access to `var/` and create that directory before starting.
Install the plist as root with mode 644 in `/Library/LaunchDaemons/`, then:

```sh
sudo launchctl bootstrap system /Library/LaunchDaemons/com.annotation-arranger.plist
```

All templates use automatic startup and restart after failure. Configure the port and tenant
in the adjacent `.env` before starting; the templates do not override these settings. On Linux/macOS, moving the install directory requires
updating the paths in the service configuration.

For remote Therefore access, put HTTPS or a named Cloudflare Tunnel in front of the local
listener. A temporary trycloudflare URL changes when restarted; cloudflared is installed
and managed separately. No tunnel credentials are included here.

## Compatibility and provenance

Choose the archive for your OS and CPU. Linux requires glibc (not Alpine/musl); builds are
tested on Ubuntu 22.04. macOS ARM64 is tested on macOS 15; macOS Intel on macOS 15;
Windows x64 on Server 2022. Older versions are not verified. Binaries are unsigned;
macOS may require approval in Privacy & Security after downloading.
`BUILD-INFO.json` identifies the source commit and runtime. Verify archives using release
SHA-256 checksums. `THIRD_PARTY_LICENSES/` and `DEPENDENCIES.json` contain dependency notices.
