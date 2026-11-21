#!/bin/bash
# Trusted runtime tool preparation. Invoked only after durable RH and budget gates.
# No fake landrun, latest refs, relaxed axioms or checker fallback is permitted.
set -euo pipefail
test "$(id -u)" = 10002
test "$PWD" = /work/ns/tools
lean --version | grep -F 'version 4.34.0-rc2'
go version
cargo --version

checkout() {
    local directory="$1" repository="$2" revision="$3"
    if [ ! -d "$directory" ]; then
        git init "$directory"
        git -C "$directory" remote add origin "$repository"
    fi
    test "$(git -C "$directory" remote get-url origin)" = "$repository"
    if [ "$(git -C "$directory" rev-parse HEAD 2>/dev/null || true)" != "$revision" ]; then
        git -C "$directory" fetch --depth 1 origin "$revision"
        git -C "$directory" checkout --detach "$revision"
    fi
    test "$(git -C "$directory" rev-parse HEAD)" = "$revision"
}

checkout landrun https://github.com/Zouuup/landrun.git 573aa723afb16bb1da2dbe24fc00df46cd0ad13b
checkout nanoda https://github.com/ammkrn/nanoda_lib.git 0da9f98feadd3a0a2ef4b3dbcf52a298a6fef929
checkout comparator https://github.com/leanprover/comparator.git 19e111e2141cf333c7daff0f64c5f24acc91dd2e

(cd landrun && CGO_ENABLED=0 go build -trimpath -o landrun ./cmd/landrun)
(cd nanoda && cargo build --release --locked)
(cd comparator && lake build lean4export comparator)
test "$(git -C comparator/.lake/packages/lean4export rev-parse HEAD)" = cacf989bd75f608700820f6afc595f32e7a99a4d
export COMPARATOR_LANDRUN=/usr/local/bin/comparator-landrun
export COMPARATOR_LEAN4EXPORT=/work/ns/tools/comparator/.lake/packages/lean4export/.lake/build/bin/lean4export
export COMPARATOR_NANODA=/work/ns/tools/nanoda/target/release/nanoda_bin
python3 /opt/ns-queue/child.py --probe-af-unix
python3 /opt/ns-queue/child.py --probe-landlock
# Real upstream negative controls, using the actual strict landrun and nanoda.
(cd comparator && lake env lean --run runtests.lean)
