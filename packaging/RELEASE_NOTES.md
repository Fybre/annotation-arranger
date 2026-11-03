Standalone Annotation Arranger REST service. No Python installation or Docker required.

Choose the archive matching your OS and CPU, extract it, then run `annotation-arranger`
(`annotation-arranger.exe` on Windows). Use `--help` for options and `--self-test` for an
offline PDF-engine test. Service configuration and setup instructions are included.

- Synchronous Therefore document retrieval, editing, saving, and verification.
- Stamp alignment: left, right, top, bottom, or auto.
- Flatten all supported PDF annotations, alone or after alignment.
- Dry runs, original-file backups, checkout protection, and no-op retries.
- Windows package includes a checksum-verified WinSW service wrapper.

Builds are unsigned. Linux builds target glibc-based systems (built on Ubuntu 22.04);
macOS builds are produced on macOS 15 ARM64 / macOS 15 Intel; Windows on Server 2022 x64.
The default tenant/category are craigdemo/392; configure these for your deployment.
Supply a Therefore token in each POST. No credentials or customer PDFs are bundled.

Verify downloads using `SHA256SUMS.txt`. All builds run offline PDF-engine and HTTP-server
smoke tests outside the source checkout before release publication.
