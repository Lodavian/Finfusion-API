"""Root-only repair of runtime-directory boot setup; no broker/order logic changes.

Input via stdin: JSON containing runtimeConfig and guardSource. Outputs sanitized evidence.
"""
from datetime import datetime, timezone
import grp
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def command(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=60)


def state(unit):
    return command('systemctl', 'is-active', unit).stdout.strip()


def main():
    assert os.geteuid() == 0
    import sys
    bundle = json.load(sys.stdin)
    content = bundle['runtimeConfig']
    assert content.strip().endswith('d /run/finfusion 0750 root finfusion -')
    guard = bundle['guardSource']; compile(guard, 'host_ready_guard.py', 'exec')
    root = Path('/var/lib/finfusion/acceptance/host-startup')
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    snapshot = root / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    snapshot.mkdir(mode=0o700)
    units = ['finfusion.service', 'finfusion-live-secrets.service', 'finfusion-node-default-off.service', 'finfusion-connectivity.service']
    evidence = {'before': {unit: state(unit) for unit in units}, 'orders': 0, 'environmentChanged': False,
                'bootTest': 'NOT_EXECUTED', 'snapshot': str(snapshot)}
    # Validate tmpfiles behavior in an isolated filesystem, including ownership and repetition.
    with tempfile.TemporaryDirectory(prefix='finfusion-tmpfiles-test-') as directory:
        trial = Path(directory); (trial/'etc').mkdir()
        gid = grp.getgrnam('finfusion').gr_gid
        (trial/'etc/group').write_text(f'root:x:0:\nfinfusion:x:{gid}:\n')
        (trial/'etc/passwd').write_text('root:x:0:0::/root:/bin/sh\n')
        fixture = trial/'runtime.conf'; fixture.write_text(content)
        for _ in range(2):
            result = command('systemd-tmpfiles', '--root='+directory, '--create', str(fixture))
            if result.returncode: raise RuntimeError('ISOLATED_TMPFILES_TEST_FAILED')
        metadata = (trial/'run/finfusion').stat()
        assert metadata.st_uid == 0 and metadata.st_gid == gid and metadata.st_mode & 0o777 == 0o750
    evidence['isolatedTmpfilesCreateRepeatPermissions'] = 'PASS'
    targets = {Path('/etc/tmpfiles.d/finfusion-runtime.conf'): content,
               Path('/opt/finfusion-ops/host_ready_guard.py'): guard}
    # Dependencies cannot be removed by empty assignments in systemd drop-ins.
    # Change only the obsolete dependency in the existing unit, preserving its Service section.
    tunnel = Path('/etc/systemd/system/finfusion-api-tunnel.service')
    original = tunnel.read_text()
    head, body = original.split('[Service]', 1)
    assert 'Wants=network-online.target finfusion-connectivity.service' in head or 'Wants=network-online.target finfusion.service' in head
    head = head.replace('Wants=network-online.target finfusion-connectivity.service', 'Wants=network-online.target finfusion.service')
    head = head.replace('After=network-online.target nginx.service finfusion-connectivity.service', 'After=network-online.target nginx.service finfusion.service')
    targets[tunnel] = head + '[Service]' + body
    evidence['tunnelServiceSectionUnchanged'] = True
    obsolete = Path('/etc/systemd/system/finfusion-api-tunnel.service.d/40-formal-api.conf')
    if obsolete.exists():
        assert not obsolete.is_symlink() and obsolete.read_text() == '[Unit]\nWants=\nWants=network-online.target finfusion.service\nAfter=finfusion.service\n'
        (snapshot/'obsolete-host-dropin.conf').write_text(obsolete.read_text())
        obsolete.unlink()
    for unit in units[1:3]:
        targets[Path('/etc/systemd/system')/(unit+'.d')/'40-runtime-parent.conf'] = (
            '[Unit]\nAfter=systemd-tmpfiles-setup.service\nRequires=systemd-tmpfiles-setup.service\n')
    for index, (target, value) in enumerate(targets.items()):
        if target.is_symlink(): raise RuntimeError('SYMLINK_TARGET_REFUSED')
        prior = target.read_bytes() if target.exists() else None
        if prior is not None: (snapshot/f'previous-{index}.bin').write_bytes(prior)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name+'.host-repair-tmp')
        assert not temporary.exists()
        temporary.write_text(value); temporary.chmod(0o644); os.replace(temporary, target)
    evidence['installedHashes'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in targets}
    for args in [('systemd-tmpfiles','--create','/etc/tmpfiles.d/finfusion-runtime.conf'), ('systemctl','daemon-reload')]:
        if command(*args).returncode: raise RuntimeError('RUNTIME_SETUP_FAILED')
    dependencies = command('systemctl','show','finfusion-api-tunnel.service','-p','Wants','--value').stdout.split()
    assert 'finfusion.service' in dependencies and 'finfusion-connectivity.service' not in dependencies
    evidence['formalTunnelDependencyVerified'] = True
    authorization = json.loads(Path('/var/lib/finfusion/formal-deployment/live/authorization.json').read_text())
    assert authorization['environment'] == 'LIVE' and authorization['ordersAuthorized'] is False
    # Existing formal unit conflicts with the legacy no-broker unit and retains its read-only wrapper.
    outcome = command('systemctl','start','finfusion.service')
    evidence['startCommandSucceeded'] = outcome.returncode == 0
    evidence['after'] = {unit: state(unit) for unit in units}
    evidence['status'] = 'PASS' if outcome.returncode == 0 and state('finfusion.service') == 'active' else 'FAIL'
    (snapshot/'result.json').write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence))
    return 0 if evidence['status'] == 'PASS' else 1


if __name__ == '__main__': raise SystemExit(main())
