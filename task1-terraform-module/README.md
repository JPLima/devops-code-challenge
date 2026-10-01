# Task 1: Terraform module

A VPC with an EC2 instance and an RDS instance, built from modules, with remote
state in S3 and locking in DynamoDB. Environments are Terraform workspaces.

Uses the `vpc`, `ec2`, `rds`, `security-group` and `kms-key` modules from
`../modules`, by git URL at tag `v1.0.0`.

## Prerequisites

Terraform 1.9+ and AWS credentials that can create VPC, EC2, RDS, S3, DynamoDB
and KMS resources. Everything defaults to `eu-west-1`.

## Running it

The backend cannot create the bucket it stores state in, so `bootstrap/` runs
first, with local state. Once per account:

```bash
cd bootstrap
terraform init
terraform apply -var="state_bucket_name=betontalent-terraform-state-<unique>"
```

It prints a `backend_block` output you can paste. The bucket is versioned,
encrypted with a customer-managed key, blocked from public access and refuses
non-TLS requests; it and the lock table both carry `prevent_destroy`.

Then point the root module at it:

```bash
cd ..
cp backend.hcl.example backend.hcl   # fill in the bucket name
terraform init -backend-config=backend.hcl
terraform workspace new staging
terraform workspace new production
```

`backend.hcl` is gitignored, since the bucket name is account-specific.

To apply:

```bash
export TF_VAR_db_password="$(openssl rand -base64 24)"

terraform workspace select staging
terraform plan  -var-file=staging.tfvars
terraform apply -var-file=staging.tfvars
```

Production is the same with `production.tfvars`.

## Environments

`local.environments` in `locals.tf` maps a workspace name to everything that
differs:

| | staging | production |
|---|---|---|
| VPC CIDR | `10.10.0.0/16` | `10.20.0.0/16` |
| Availability zones | 2 | 3 |
| NAT gateways | 1, shared | one per AZ |
| EC2 instance type | `t3.micro` | `t3.small` |
| RDS instance class | `db.t4g.micro` | `db.t4g.small` |
| RDS multi-AZ | no | yes |
| Backup retention | 1 day | 30 days |
| Deletion protection | off | on |
| Final snapshot on destroy | skipped | taken |

The lookup has no default, so an unknown workspace fails at plan time instead
of deploying the wrong sizing. That includes `default`, which means `validate`
needs a workspace too:

```bash
TF_WORKSPACE=staging terraform validate
```

`TF_WORKSPACE` works without an initialised backend, which is what makes it
usable in CI.

## Security groups

The web tier rules come from `var.web_ingress_cidrs`, a map keyed by network
name:

```hcl
web_ingress_cidrs = {
  "office-lisbon" = "203.0.113.10/32"
  "vpn-gateway"   = "203.0.113.64/26"
}
```

Each entry becomes its own `aws_vpc_security_group_ingress_rule` addressed by
its key. Adding or removing one network plans a single create or destroy. A
variable validation rejects `0.0.0.0/0`.

The database group has one ingress rule, referencing the web tier group by id
instead of a CIDR. It has no egress rules at all.

## Design choices

I used workspaces because the challenge names them as the bonus and because
both environments live in the same account. If they were separate accounts I
would have split the root configuration instead, and `locals.tf` is where I
would start.

Subnet CIDRs come from `cidrsubnet` rather than a list, so I only set the VPC
CIDR per environment. Public subnets take the low half of the plan, which
keeps existing subnets numbered the same when I add an AZ. Subnets are keyed by
AZ name rather than index; removing a zone destroys one subnet instead of
shifting the rest.

The AMI is an `aws_ami` data source with `ignore_changes = [ami]`. Hardcoding
an id ties the config to one region and one patch level, but resolving it at
plan time without the ignore would replace a running instance every time
Amazon publishes an image.

RDS gets its own parameter group even with almost nothing overridden, because
the default group cannot be modified and the first parameter anyone needs to
change would otherwise force a replacement. `final_snapshot_identifier` uses
`timestamp()` under `ignore_changes` for the same reason in reverse: without
the ignore it would show a diff on every plan.

The RDS password is a sensitive variable here rather than a Secrets Manager
secret. Task 1 does not ask for Secrets Manager and task 2 does, so the
contrast is visible between the two. It is redacted from plan output but it is
still in state, which is why the state bucket is encrypted with a
customer-managed key.

Tags are set once in `default_tags` on the provider.

A second apply with no changes plans nothing: no bare `timestamp()`, the AMI
lookup is pinned by `ignore_changes`, the snapshot name is ignored, and there
are no random resources without stable inputs.

## Outputs

`vpc_id`, `public_subnet_ids`, `private_subnet_ids`, `ec2_public_ip`,
`ec2_public_dns`, `ec2_private_dns`, `rds_endpoint`, `rds_address`, `rds_port`,
`web_security_group_id`, `web_ingress_rule_ids`, `db_security_group_id`,
`kms_key_arn`, `environment`.

The RDS endpoint is a hostname on a private subnet, so it is not marked
sensitive. The password never appears in an output.
