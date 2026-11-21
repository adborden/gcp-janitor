import asyncio
import datetime
import logging

from google.api_core import exceptions
from google.cloud.kms_v1 import KeyManagementServiceAsyncClient

from . import kms
from .config import Config

log = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 3600  # seconds

# List of services the controller supports. This can be extended in the future to include other services.
SUPPORTED_SERVICES = ["kms"]

KMS_ENABLED = "ENABLED"
KMS_DISABLED = "DISABLED"
KMS_DELETED = "DESTROY_SCHEDULED"

ACTION_DISABLE = "disable"
ACTION_DELETE = "delete"


async def main(args):
    log.info("Starting controller")

    # libresource.().
    #
    config = Config.load(args.config)
    config.general.project_id = args.project or config.general.project_id

    if args.dry_run:
        log.info("Dry run mode enabled. No changes will be made.")

    client = await kms.get_client()

    while True:
        try:
            try:
                delete_threshold = datetime.datetime.now(
                    datetime.timezone.utc
                ) - datetime.timedelta(days=30)
                await perform_action(
                    args, client, delete_threshold, action=ACTION_DELETE
                )

                disable_threshold = datetime.datetime.now(
                    datetime.timezone.utc
                ) - datetime.timedelta(days=14)
                await perform_action(
                    args, client, disable_threshold, action=ACTION_DISABLE
                )
            except (exceptions.GoogleAPICallError, exceptions.RetryError):
                # RetryError is raised once KMS_RETRY times out (e.g. sustained
                # rate limiting); GoogleAPICallError covers non-retryable API
                # errors such as PermissionDenied. Try again next iteration.
                log.exception("KMS API error, will retry next iteration")

            # sleep before next iteration
            await asyncio.sleep(DEFAULT_POLL_INTERVAL)
        except asyncio.CancelledError:
            log.info("Controller cancelled, exiting")
            return


async def perform_action(
    args, client, threshold: datetime.datetime, action=ACTION_DISABLE
):
    log.info(
        "Looking for stale key versions action=%s threshold=%s",
        action,
        threshold,
    )
    project_id = args.project
    location_id = args.location or "us-west1"
    keyring_id = args.keyring
    key_id = args.key

    if action == ACTION_DELETE:
        state = KMS_DISABLED
        target_state = KMS_DELETED
    elif action == ACTION_DISABLE:
        state = KMS_ENABLED
        target_state = KMS_DISABLED
    else:
        raise Exception(f"Unknown action: {action}")

    async for crypto_key_version in kms.iter_crypto_key_versions(
        client,
        parent=f"projects/{project_id}/locations/{location_id}/keyRings/{keyring_id}/cryptoKeys/{key_id}",
        filter=f"state = {state}",
    ):
        log.debug(
            "Found crypto key version: %s, created=%s, generated=%s",
            crypto_key_version.name,
            crypto_key_version.create_time,
            crypto_key_version.generate_time,
        )
        if not crypto_key_version.state.name == state:
            log.warning(
                f"Unexpected state={crypto_key_version.state.name} for crypto key version: %s",
                crypto_key_version.name,
            )
            continue
        if crypto_key_version.create_time is None:
            log.warning(
                "Crypto key version %s has no create_time, skipping",
                crypto_key_version.name,
            )
            continue
        if crypto_key_version.create_time < threshold:
            log.info(
                "Crypto key version is older than threshold, deleting it action=%s threshold=%s create_time=%s name=%s",
                action,
                threshold,
                crypto_key_version.create_time,
                crypto_key_version.name,
            )

            try:
                if action == ACTION_DISABLE:
                    await kms.crypto_key_version_set_state(
                        client,
                        crypto_key_version,
                        target_state,
                        args.dry_run,
                    )
                elif action == ACTION_DELETE:
                    await kms.destroy_crypto_key_version(
                        client,
                        crypto_key_version,
                        args.dry_run,
                    )
                else:
                    raise Exception(f"Unknown action: {action}")
            except exceptions.FailedPrecondition as e:
                # The version's state changed since it was listed, e.g. a
                # retried destroy that had already been applied, or someone
                # re-enabled/destroyed it out of band.
                log.warning(
                    "Skipping crypto key version, state changed action=%s name=%s error=%s",
                    action,
                    crypto_key_version.name,
                    e,
                )
            except (exceptions.GoogleAPICallError, exceptions.RetryError):
                log.exception(
                    "Failed to update crypto key version action=%s name=%s",
                    action,
                    crypto_key_version.name,
                )
                # If retries were exhausted, abort the batch
                break
