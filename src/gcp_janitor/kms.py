"""Google Cloud KMS management and traversal utilities for gcp-janitor."""

from collections.abc import AsyncIterator, Sequence
import logging
from typing import NamedTuple

from google.cloud.kms import (
    CryptoKey,
    CryptoKeyVersion,
    KeyManagementServiceAsyncClient,
    KeyManagementServiceClient,
    KeyRing,
)

log = logging.getLogger(__name__)


class KMSItem(NamedTuple):
    """Represents a discovered KMS key version and its parent hierarchy."""

    key_ring: KeyRing
    crypto_key: CryptoKey
    version: CryptoKeyVersion


async def crypto_key_version_set_state(
    client,
    crypto_key_version: CryptoKeyVersion,
    state: CryptoKeyVersion.CryptoKeyVersionState = CryptoKeyVersion.CryptoKeyVersionState.DISABLED,
    dry_run: bool = True,
) -> None:
    """
    Disable a CryptoKeyVersion.

    Args:
        crypto_key_version: The CryptoKeyVersion to disable.

    Returns:
        CryptoKeyVersion: The disabled version.
    """
    if dry_run:
        return

    # Build the update mask.
    update_mask = {"paths": ["state"]}

    # Update the state
    crypto_key_version.state = state

    # Call the API to update the key version
    updated_version = await client.update_crypto_key_version(
        request={
            "crypto_key_version": crypto_key_version,
            "update_mask": update_mask,
        }
    )
    log.info("Updated key version: %s, state=%s", updated_version.name, state)


async def destroy_crypto_key_version(
    client,
    crypto_key_version: CryptoKeyVersion,
    dry_run: bool = True,
) -> None:
    """
    Disable a CryptoKeyVersion.

    Args:
        crypto_key_version: The CryptoKeyVersion to disable.

    Returns:
        CryptoKeyVersion: The disabled version.
    """
    if dry_run:
        return

    # Build the update mask.
    update_mask = {"paths": ["state"]}

    # Call the API to update the key version
    destroyed_version = await client.destroy_crypto_key_version(
        request={
            "name": crypto_key_version.name,
        }
    )
    log.info("Desotryed version=%s", destroyed_version.name)


async def get_client():
    return KeyManagementServiceAsyncClient()


async def iter_key_rings(
    client: KeyManagementServiceAsyncClient,
    parent: str,
) -> AsyncIterator[KeyRing]:
    """
    Asynchronously iterate over all KeyRings within a location.

    Args:
        client: The async KeyManagementServiceClient.
        parent: The resource name of the location, in the format
            `projects/*/locations/*`.

    Yields:
        KeyRing: Discovered key ring resources.
    """
    log.debug("Listing key rings in parent: %s", parent)
    pager = await client.list_key_rings(parent=parent)
    async for key_ring in pager:
        log.debug("Found KeyRing: %s", key_ring.name)
        yield key_ring


async def iter_crypto_keys(
    client: KeyManagementServiceAsyncClient,
    parent: str,
) -> AsyncIterator[CryptoKey]:
    """
    Asynchronously iterate over all CryptoKeys within a KeyRing.

    Args:
        client: The async KeyManagementServiceClient.
        parent: The resource name of the key ring, in the format
            `projects/*/locations/*/keyRings/*`.

    Yields:
        CryptoKey: Discovered crypto key resources.
    """
    log.debug("Listing crypto keys in key ring: %s", parent)
    pager = await client.list_crypto_keys(parent=parent)
    async for crypto_key in pager:
        log.debug(
            "Found CryptoKey: %s (labels=%s)", crypto_key.name, dict(crypto_key.labels)
        )
        yield crypto_key


async def iter_crypto_key_versions(
    client: KeyManagementServiceAsyncClient,
    parent: str,
    filter: str | None = None,
) -> AsyncIterator[CryptoKeyVersion]:
    """
    Asynchronously iterate over all CryptoKeyVersions within a CryptoKey.

    Args:
        client: The async KeyManagementServiceClient.
        parent: The resource name of the crypto key, in the format
            `projects/*/locations/*/keyRings/*/cryptoKeys/*`.
        filter: Optional filter expression (e.g. 'state != DISABLED AND state != DESTROY_SCHEDULED').

    Yields:
        CryptoKeyVersion: Discovered crypto key version resources.
    """
    log.debug("Listing key versions in crypto key: %s (filter=%s)", parent, filter)
    request = {"parent": parent}
    if filter:
        request["filter"] = filter

    pager = await client.list_crypto_key_versions(request=request)
    async for version in pager:
        log.debug(
            "Found CryptoKeyVersion: %s (state=%s)",
            version.name,
            version.state.name,
        )
        yield version


async def iter_key_versions(
    client: KeyManagementServiceAsyncClient,
    parent: str,
    filter: str | None = None,
) -> AsyncIterator[KMSItem]:
    """
    Recursively loop over all key rings, crypto keys, and key versions in a location.

    Args:
        client: The async KeyManagementServiceClient.
        parent: The resource name of the location, in the format
            `projects/*/locations/*`.
        filter: Optional filter expression passed to iter_crypto_key_versions.

    Yields:
        KMSItem: Tuples of (key_ring, crypto_key, version).
    """
    async for key_ring in iter_key_rings(client, parent):
        async for crypto_key in iter_crypto_keys(client, key_ring.name):
            async for version in iter_crypto_key_versions(
                client, crypto_key.name, filter=filter
            ):
                yield KMSItem(
                    key_ring=key_ring,
                    crypto_key=crypto_key,
                    version=version,
                )


async def loop_kms_resources(
    client: KeyManagementServiceAsyncClient,
    project_id: str,
    locations: Sequence[str],
    filter: str | None = None,
) -> AsyncIterator[KMSItem]:
    """
    Loop over all key rings, crypto keys, and key versions across multiple locations.

    Args:
        client: The async KeyManagementServiceClient.
        project_id: GCP project ID.
        locations: Sequence of location identifiers (e.g. ["global", "us-central1"]).
        filter: Optional filter expression passed to iter_crypto_key_versions.

    Yields:
        KMSItem: Tuples of (key_ring, crypto_key, version).
    """
    for location in locations:
        parent = f"projects/{project_id}/locations/{location}"
        log.info("Scanning KMS resources in location: %s", parent)
        async for item in iter_key_versions(client, parent, filter=filter):
            yield item


# Aliases for convenience / controller compatibility
get_keyrings = iter_key_rings
get_crypto_keys = iter_crypto_keys
get_crypto_key_versions = iter_crypto_key_versions


def disable_key_version(
    project_id: str, location_id: str, key_ring_id: str, key_id: str, version_id: str
) -> CryptoKeyVersion:
    """
    Disable a key.

    Args:
        project_id (string): Google Cloud project ID (e.g. 'my-project').
        location_id (string): Cloud KMS location (e.g. 'us-east1').
        key_ring_id (string): ID of the Cloud KMS key ring (e.g. 'my-key-ring').
        key_id (string): ID of the key to use (e.g. 'my-key').
        version_id (string): ID of the key version to disable (e.g. '1').

    Returns:
        CryptoKeyVersion: The version.

    """

    # Create the client.
    client = KeyManagementServiceClient()

    # Build the key version name.
    key_version_name = client.crypto_key_version_path(
        project_id, location_id, key_ring_id, key_id, version_id
    )

    key_version = {
        "name": key_version_name,
        "state": CryptoKeyVersion.CryptoKeyVersionState.DISABLED,
    }

    # Build the update mask.
    update_mask = {"paths": ["state"]}

    # Call the API.
    disabled_version = client.update_crypto_key_version(
        request={"crypto_key_version": key_version, "update_mask": update_mask}
    )

    print(f"Disabled key version: {disabled_version.name}")
    return disabled_version
