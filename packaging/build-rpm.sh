#!/usr/bin/env bash
# Build the Platesmith RPM in a Fedora container (no rpmbuild needed on host).
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(grep -m1 '^version' pyproject.toml | cut -d'"' -f2)
FEDORA=${FEDORA:-44}

rm -rf dist/sdist dist/rpm
uv build --sdist --out-dir dist/sdist
mkdir -p dist/rpm

podman run --rm \
  -v "$PWD/dist/sdist:/in:ro,z" \
  -v "$PWD/packaging:/pkg:ro,z" \
  -v "$PWD/dist/rpm:/out:z" \
  "registry.fedoraproject.org/fedora:$FEDORA" bash -euc "
    dnf -q install -y rpm-build rpmdevtools python3-devel pyproject-rpm-macros \
        systemd-rpm-macros python3-pytest python3-httpx 'dnf-command(builddep)'
    rpmdev-setuptree
    cp /in/platesmith-$VERSION.tar.gz /pkg/platesmith.service ~/rpmbuild/SOURCES/
    cp /pkg/platesmith.spec ~/rpmbuild/SPECS/
    dnf -q builddep -y ~/rpmbuild/SPECS/platesmith.spec
    # %generate_buildrequires is iterative: rpmbuild emits a .buildreqs
    # package with the next round of deps until everything is satisfied.
    for i in 1 2 3 4 5; do
      rm -f ~/rpmbuild/SRPMS/*.buildreqs.nosrc.rpm
      if rpmbuild -ba ~/rpmbuild/SPECS/platesmith.spec; then break; fi
      reqs=(~/rpmbuild/SRPMS/*.buildreqs.nosrc.rpm)
      [ -e \"\${reqs[0]}\" ] || exit 1
      dnf -q builddep -y \"\${reqs[@]}\"
    done
    cp ~/rpmbuild/RPMS/noarch/*.rpm ~/rpmbuild/SRPMS/platesmith-*.src.rpm /out/
  "

echo
echo "Built:"
ls -la dist/rpm/
