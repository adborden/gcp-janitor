# gcp-janitor

Policy based resource cleanup in your GCP project.

## Usage

```bash
uv run gcp-janitor --dry-run --project cloud-294216 --keyring vault-fl-a14n-net --key vault-fl-a14n-net
```

## Development

## KMS key versions

List out the current key versions to verify.

```bash
gcloud auth login
gcloud kms keys versions list --location us-west1 --keyring vault-fl-a14n-net --key vault-fl-a14n-net
```
