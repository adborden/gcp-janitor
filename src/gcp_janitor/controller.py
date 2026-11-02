import asyncio
import datetime
import logging

from google.cloud.kms_v1 import KeyManagementServiceAsyncClient

from . import kms

log = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 3600  # seconds

# List of services the controller supports. This can be extended in the future to include other services.
SUPPORTED_SERVICES = ["kms"]

KMS_ENABLED = "ENABLED"
KMS_DISABLED = "DISABLED"
KMS_DELETED = "DESTROY_SCHEDULED"


async def main(args):
    log.info("Starting controller")

    # libresource.().

    if args.dry_run:
        log.info("Dry run mode enabled. No changes will be made.")

    project_id = args.project
    location_id = args.location or "us-west1"
    keyring_id = args.keyring
    key_id = args.key

    disable_threshold = datetime.datetime.now(
        datetime.timezone.utc
    ) - datetime.timedelta(days=14)
    delete_threshold = datetime.datetime.now(
        datetime.timezone.utc
    ) - datetime.timedelta(days=30)

    client = await kms.get_client()

    # delete resources
    async for crypto_key_version in kms.iter_crypto_key_versions(
        client,
        parent=f"projects/{project_id}/locations/{location_id}/keyRings/{keyring_id}/cryptoKeys/{key_id}",
        filter=f"state = {KMS_DISABLED}",
    ):
        log.debug(
            "Found crypto key version: %s, created=%s, generated=%s",
            crypto_key_version.name,
            crypto_key_version.create_time,
            crypto_key_version.generate_time,
        )
        if not crypto_key_version.state.name == KMS_DISABLED:
            log.warning(
                "Unexpected state={crypto_key_version.state.name} for crypto key version: %s",
                crypto_key_version.name,
            )
            continue
        if crypto_key_version.create_time is None:
            log.warning(
                "Crypto key version %s has no create_time, skipping",
                crypto_key_version.name,
            )
            continue
        if crypto_key_version.create_time < delete_threshold:
            log.info(
                "Crypto key version %s is older than threshold, deleting it",
                crypto_key_version.name,
            )
            await kms.destroy_crypto_key_version(
                client,
                crypto_key_version,
                args.dry_run,
            )

    # disable resources
    async for crypto_key_version in kms.iter_crypto_key_versions(
        client,
        parent=f"projects/{project_id}/locations/{location_id}/keyRings/vault-fl-a14n-net/cryptoKeys/vault-fl-a14n-net",
        filter=f"state = {KMS_ENABLED}",
    ):
        disable_threshold = datetime.datetime.now(
            datetime.timezone.utc
        ) - datetime.timedelta(days=14)

        log.debug(
            "Found crypto key version: %s, created=%s, generated=%s",
            crypto_key_version.name,
            crypto_key_version.create_time,
            crypto_key_version.generate_time,
        )
        if not crypto_key_version.state.name == KMS_ENABLED:
            log.warning(
                "Unexpected state={crypto_key_version.state.name} for crypto key version: %s",
                crypto_key_version.name,
            )
            continue

        if crypto_key_version.create_time is None:
            log.warning(
                "Crypto key version %s has no create_time, skipping",
                crypto_key_version.name,
            )
            continue

        if crypto_key_version.create_time < disable_threshold:
            log.info(
                "Crypto key version %s is older than threshold, disabling it",
                crypto_key_version.name,
            )
            await kms.crypto_key_version_set_state(
                client,
                crypto_key_version,
                KMS_DELETED,
                args.dry_run,
            )

    # sleep before next iteration
    await asyncio.sleep(DEFAULT_POLL_INTERVAL)
