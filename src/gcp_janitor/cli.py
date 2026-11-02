import argparse
import asyncio
import logging

from . import controller

logging.basicConfig(level=logging.INFO)

log = logging.getLogger(__name__)


def parse_arguments(parser):
    args = parser.parse_args()
    return args


def get_parser():
    parser = argparse.ArgumentParser(description="GCP Janitor CLI")

    parser.add_argument(
        "-c",
        "--config",
        default=None,
        action="store",
        help="Path to TOML configuration file",
    )

    parser.add_argument(
        "--dry-run",
        default=False,
        action="store_true",
        help="Perform a dry run without making any changes",
    )

    parser.add_argument(
        "--verbose",
        default=False,
        action="store_true",
        help="Include debug logging",
    )

    parser.add_argument(
        "--project",
        default=None,
        action="store",
        help="GCP project ID to scan for resources",
    )

    parser.add_argument(
        "--location",
        default=None,
        action="store",
        help="GCP location ID to scan for resources",
    )

    parser.add_argument(
        "--keyring",
        default=None,
        action="store",
        help="GCP Cloud KMS keyring ID to monitor",
    )

    parser.add_argument(
        "--key",
        default=None,
        action="store",
        help="GCP Cloud KMS key ID to monitor",
    )

    return parser


async def run_controller(args):
    await controller.main(args)


def main():
    parser = get_parser()
    args = parse_arguments(parser)

    if args.verbose:
        logging.getLogger(__package__).setLevel(logging.DEBUG)

    asyncio.run(run_controller(args))


if __name__ == "__main__":
    main()
