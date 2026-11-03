# Annotation Arranger executable

This archive includes a standalone executable with Python and the required PDF libraries.
No Python installation or Docker is needed on the destination machine.

## Run

```sh
./annotation-arranger --help
./annotation-arranger --self-test
./annotation-arranger --host 127.0.0.1 --port 8765 --backup-dir ./var/backups
```

On Windows use `.\annotation-arranger.exe` instead of `./annotation-arranger`.
Keep backups in a private writable directory. Command-line options override environment
variables; `settings.example.env` lists them but is not loaded automatically.
Defaults permit only craigdemo category 392. Configure `--tenant`, `--base-url`, and
`--allowed-categories` for other deployments. No credentials are stored in the executable.

`GET /health` reports process health. `GET /docs` opens the API documentation.
`POST /arrange-annotations` accepts JSON:

```json
{"docNo": 12345, "token": "YOUR_JWT", "alignment": "bottom", "flatten": false, "dryRun": true}
```

Omit `alignment` with `flatten: true` to flatten alone. Set `dryRun: false` to save.
Without flattening or explicit alignment, alignment defaults to auto. The response is
returned after saving and verifying, with a success/error status. Original PDFs are backed
up before replacement. Flattened annotations become static page content and cannot be
realigned later; unsupported appearances fail without saving.

## Background service

**Windows:** retain the whole extracted folder. From an administrator PowerShell:

```powershell
New-Item -ItemType Directory -Force var\backups
cd service
.\annotation-arranger-service.exe install
.\annotation-arranger-service.exe start
```

The XML uses paths relative to its own location. Use Windows Services to configure a
suitable service account and grant it access to the application and backup/log directories.
To stop/remove: `annotation-arranger-service.exe stop` and `annotation-arranger-service.exe uninstall`.

**Linux:** copy the extracted folder to `/opt/annotation-arranger`, create an
`annotation-arranger` system account, and ensure it can execute the binary. The bundled
unit creates private state under `/var/lib/annotation-arranger`:

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

All templates use automatic startup and restart after failure. Adjust the port and tenant
in the template before installation. On Linux/macOS, moving the install directory requires
updating the paths in the service configuration.

For remote Therefore access, put HTTPS or a named Cloudflare Tunnel in front of the local
listener. A temporary trycloudflare URL changes when restarted; cloudflared is installed
and managed separately. No tunnel credentials are included here.

## Compatibility and provenance

Choose the archive for your OS and CPU. Linux requires glibc (not Alpine/musl); builds are
tested on Ubuntu 22.04. macOS ARM64 is tested on macOS 14; macOS Intel on macOS 15;
Windows x64 on Server 2022. Older versions are not verified. Binaries are unsigned;
macOS may require approval in Privacy & Security after downloading.
`BUILD-INFO.json` identifies the source commit and runtime. Verify archives using release
SHA-256 checksums. `THIRD_PARTY_LICENSES/` and `DEPENDENCIES.json` contain dependency notices.
