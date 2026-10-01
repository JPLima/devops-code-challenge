# Task 2: AWS cloud security

A private workload with the controls the challenge asks for: segmented network,
no inbound access, least-privilege IAM, encryption on anything that stores
data, CloudTrail, AWS Config, and alarms.

Uses `vpc`, `ec2`, `security-group`, `kms-key` (three times),
`iam-instance-role`, `cloudtrail`, `aws-config`, `security-alerting` and
`secret` from `../modules`. The `vpc` and `ec2` modules are the same ones task 1
uses; the difference is configuration.

## Prerequisites

Terraform 1.9+, and an account where AWS Config is not already recording, since
there is one recorder per region.

## Deploying

```bash
terraform init
terraform plan
terraform apply
```

To get the alarms by email, pass addresses. Each recipient has to click a
confirmation link; Terraform cannot do that for them.

```bash
terraform apply -var='security_notification_emails=["you@example.com"]'
```

There is no SSH. To reach the instance:

```bash
aws ssm start-session --target "$(terraform output -raw instance_id)"
```

## Security practices implemented

### Network

Public subnets hold the NAT gateways and nothing else, with
`map_public_ip_on_launch` false even there.

The private subnets reach AWS APIs through VPC endpoints: interface endpoints
for `ssm`, `ssmmessages` and `ec2messages`, and a gateway endpoint for S3. That
traffic never crosses the NAT gateway or the internet. The gateway endpoint is
also free, where an interface endpoint for S3 bills per hour and per gigabyte.

VPC Flow Logs capture `ALL` traffic, not just rejects, because accepted traffic
is what tells you how far someone got. The log group is encrypted with a
customer-managed key and its role is scoped to that one group.

### Compute

The instance is in a private subnet with `associate_public_ip_address = false`
and a security group with no ingress rules at all.

Access is Session Manager. I read "only necessary ports" literally: the number
of inbound ports this workload needs is zero. A bastion on port 22 would add a
host to patch, a key to distribute and revoke, and an audit trail in `sshd`
logs instead of CloudTrail. With SSM every session is a CloudTrail event and
access is an IAM decision.

Egress is scoped to the VPC CIDR on 443, so a compromised instance cannot call
out to an arbitrary address.

IMDSv2 is required with a hop limit of 1. Version 1 answers an unauthenticated
`GET`, which is how an SSRF bug in an application turns into leaked role
credentials. The hop limit stops a container on the host reaching the metadata
service through the bridge.

### IAM

The workload policy is hand-written as an `aws_iam_policy_document` scoped to
one bucket, one prefix and one key. There is no `Resource = "*"` in it.

The one managed policy is `AmazonSSMManagedInstanceCore`, the documented
contract for Session Manager, which changes as the agent does.

The policy grants `kms:Decrypt` and `kms:GenerateDataKey` on the bucket's key,
conditioned on `kms:ViaService` being S3. Without that, every `GetObject`
against the encrypted bucket fails with `AccessDenied` and the error names S3,
not KMS.

### Encryption

Three customer-managed keys, all with rotation on:

| Key | Encrypts |
|---|---|
| `observability` | CloudTrail objects and log group, flow logs, Config data |
| `data` | EBS root volume, application data bucket |
| `secrets` | Secrets Manager secrets |

One key per purpose keeps each key policy readable, and revoking access to logs
does not lock the workload out of its own data.

Every bucket has SSE-KMS by default, versioning, public access blocked and
`BucketOwnerEnforced` ownership, which disables ACLs. Each bucket policy denies
non-TLS requests, and the data bucket also denies a `PutObject` that asks for
any key but ours.

### Audit

CloudTrail is multi-region with global service events and log file validation.
A single-region trail is a blind spot, and IAM reports into one region only, so
without `include_global_service_events` those events are simply absent.

It writes to S3 for durability and to CloudWatch Logs so metric filters have
something to read. Advanced event selectors capture S3 data events as well as
management events, since management events record that a bucket was created,
not that its contents were read.

### Detection

CloudTrail records everything and alerts on nothing, so `security-alerting` has
six metric filters, each with an alarm:

| Detection | Fires when |
|---|---|
| `unauthorized-api-calls` | 5 or more denied calls in 5 minutes |
| `root-account-usage` | The root user does anything |
| `console-login-without-mfa` | A console sign-in succeeds without MFA |
| `iam-policy-changes` | Any policy is created, attached, changed or deleted |
| `cloudtrail-config-changes` | The trail is changed, stopped or deleted |
| `security-group-changes` | A rule is authorised or revoked outside Terraform |

The challenge asks for one alarm, on unauthorised actions. I added the other
five because they are the same mechanism and the trail is already there.

Each metric transformation sets `default_value = 0`. Without it the metric has
no datapoint when nothing matches and the alarm sits in `INSUFFICIENT_DATA`
rather than `OK`.

`security-group-changes` fires on my own applies. That is intentional: a rule
changed by hand and a rule changed by Terraform look identical in CloudTrail
and only one of them is fine.

### Configuration recording

AWS Config records every supported resource type including global ones, and
runs 20 managed rules. CloudTrail answers who changed something; Config answers
what it looks like now.

### Secrets

The database credential is generated by `random_password` and written straight
to Secrets Manager, so nobody types it. The instance role may read that one ARN.

`random_password` keeps its result in state as well, so Secrets Manager buys
rotation, access control and audit here, not keeping the value out of state.
Only a rotation lambda replacing the initial value does that.

## The root user

The challenge lists "disable root user". That cannot be done through Terraform
or any AWS API. What is codifiable:

- `root-account-mfa-enabled`, a Config rule
- `root-access-key-check`, a Config rule
- `root-account-usage`, an alarm on any root activity

Removing root access keys and enabling MFA are console actions someone performs
once. These tell you whether that happened and whether it stayed that way.

## Verification

```bash
terraform fmt -check -recursive
terraform init -backend=false && terraform validate
tflint --recursive
checkov
```

Checkov passes with no failures. The skips are inline with a reason each. The
substantive ones:

`CKV_AWS_109`, `CKV_AWS_111` and `CKV_AWS_356` fire on the KMS key policy.
Every key policy needs a statement granting the account root `kms:*` on `*`,
because IAM policies alone cannot grant access to a KMS key. Without it the key
is unmanageable and AWS support is the only way back. A key policy's `Resource`
is always `*`, meaning that key.

`CKV_AWS_252` wants CloudTrail to define an SNS topic. `sns_topic_name`
notifies once per delivered log file, which is noise; detection runs off the
log group instead.

`CKV_AWS_394` wants availability zone ids pinned, which would tie the module to
one region. The `opt-in-status` filter excludes Local Zones and Wavelength,
which is the expansion that matters.

Four more are suppressed repository-wide in `.checkov.yaml`, each with its
reason there: S3 access logging, cross-region replication, bucket event
notifications and Secrets Manager rotation. They are scope decisions rather
than oversights.

Use the same checkov the pipeline does. A Homebrew install runs a smaller set
of checks than the pip package, which is why the workflow pins
`checkov==3.3.20` from pip.

## Design choices

No bastion host, discussed above. The trade is a hard dependency on the SSM
agent and the three interface endpoints; if the agent breaks the instance is
unreachable and you replace it.

Three KMS keys rather than one, for blast radius and readable key policies.

The trail bucket lives in the `cloudtrail` module and the Config bucket in
`aws-config`, because each needs a service-specific bucket policy. The
application data bucket is in `main.tf` because it belongs to this root
module's composition.

The `ec2` module does not create its security group. Task 1 needs a group
allowing HTTPS from named networks and this one needs a group with no ingress
at all; a flag would mean a module that sometimes owns a group and sometimes
does not, with outputs that are sometimes null.

`prevent_destroy` on the CloudTrail bucket means `terraform destroy` fails
until someone removes the lifecycle block. That friction is the point.

Bucket names are suffixed with the account id rather than a random id, so they
survive a state rebuild.
