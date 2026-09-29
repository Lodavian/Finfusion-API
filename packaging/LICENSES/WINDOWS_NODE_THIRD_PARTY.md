# Finfusion Windows Node third-party components

The node bundle must ship the license files supplied with its exact Debian 12
rootfs, Casdoor, cloudflared, age, PostgreSQL, Python runtime, .NET runtime and
all Python wheels. `build_windows_node.ps1` records exact artifacts and hashes;
release signing must not proceed until the release operator has copied those
licenses into the final bundle and completed legal review.

Casdoor is consumed from the complete official 3.143.0 Linux x86_64 release
archive so its web assets and upstream notices remain associated with the
runtime. Webull OpenAPI Python SDK remains pinned to 2.0.18. No dependency may use an
auto-update channel inside the node; updates are versioned, hash-checked and
signed bundles applied while the node is inactive.
