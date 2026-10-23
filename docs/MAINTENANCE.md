# Maintenance and releases

The scheduled workflow checks upstream stable releases every Monday at 06:23 UTC.
It proposes only newer numeric releases; it does not track development branches,
merge PRs, approve reviews, update toolchains silently, publish releases or flash
hardware. ArduPilot proposals require matching Copter/Plane versions and commits.
A patch conflict or compiler incompatibility blocks the build for human review.

The updater needs repository workflow permission to create pull requests.
A PR created with GITHUB_TOKEN does not itself trigger normal PR workflows,
so the updater explicitly dispatches the build workflow on its candidate branch.
Closed proposals are not automatically reopened. Enable Actions failure
notifications; schedules may be delayed or disabled by GitHub for inactive repos.

## Review an update

1. Read upstream release notes and compare the old/new commits in the lock.
2. Review patch applicability and all changes to sensor, serial, storage,
   timer/DMA, bootloader and parameter behavior.
3. Require the complete **All firmware checks** status on the current PR commit.
4. Review every target manifest and any change in flash usage.
   Artifact checks require at least 16 KiB of physical flash headroom; linker
   scripts separately enforce reserved parameter/config regions.
5. Re-run the relevant physical bench checks; do not inherit qualification
   merely because the previous release passed.
6. Merge only after human review. The main push produces a fresh build.

## Publish

In Actions, manually run **Publish approved prerelease** from main, supplying
the successful main-push build run ID for the current main commit and a new
tag such as v0.1.0-rc1. It rejects failed, partial, dirty or mismatched builds,
verifies artifact checksums and publishes only a hardware-unvalidated prerelease.
It does not overwrite existing releases. No automatic stable release exists.

Artifacts expire after 30 days; a published release provides persistent download
links and SHA256SUMS. Download the matching manifest and keep it with the firmware.
Releases also include `companion-apb.tar.gz`, exported from the same checked
commit, with installation/rollback instructions. Its checksum is in SHA256SUMS.
CI runs companion protocol/storage tests alongside firmware checks. Changes to
the companion's wire protocol or runtime dependencies require host fault tests
and a fresh physical bench check; neither inherits qualification from firmware CI.
Source reproduction requires the exact upstream commit/submodule pins in the
lock plus this repository at the manifest's port revision. Port source and GPL
license are included in tagged releases. Build tools are checksum-verified;
host OS packages are not a bit-for-bit container snapshot, so do not infer
byte-identical outputs across arbitrary host environments.

## Scope and licensing

This is a focused downstream overlay/build repository, not a GitHub network
fork of the entire upstream tree. It retains upstream code attribution and
GPL-3.0-or-later licensing. Changes were AI-assisted and require human review.
We prefer small fixes that can be offered upstream after validation. No upstream
PR is opened automatically, and no Orqa endorsement or flight certification is
claimed.
