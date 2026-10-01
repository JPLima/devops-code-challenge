# DevOps Code Challenge

| Task | | |
|---|---|---|
| 1 | VPC, EC2 and RDS from modules, S3 backend with DynamoDB locking, workspaces for environments | [`task1-terraform-module/`](task1-terraform-module/) |
| 2 | Private workload, least-privilege IAM, encryption, CloudTrail, Config, alarms | [`task2-aws-security/`](task2-aws-security/) |
| 3 | A broken Lambda and Terraform project, fixed | [`task3-lambda-troubleshooting/`](task3-lambda-troubleshooting/) |

Each task has its own README. For task 3 the writeup is
[`FIXES.md`](task3-lambda-troubleshooting/FIXES.md).

## Modules

I put every module in `modules/` and consume them by git URL at a tag. A root
configuration then keeps working the way it did when it was pinned:

```hcl
module "vpc" {
  source = "git::https://github.com/JPLima/devops-code-challenge.git//modules/vpc?ref=v1.0.0"
  ...
}
```

The downside is that editing a module changes nothing until you tag and push
it. To iterate I point the source at `../modules/vpc` and switch it back before
committing. References between modules stay relative, so a module fetched from
a tag uses its own version of its dependencies.

Tasks 1 and 2 share `vpc`, `ec2`, `security-group` and `kms-key`. What makes
task 1 a public web tier and task 2 a private workload is configuration, not
separate copies. Task 3 uses none of them, because its brief limits it to the
AWS services the broken project already had.

A git tag is a mutable pointer, so this only holds up with a tag protection
rule on `v*`. Checkov's `CKV_TF_1` would rather see a commit SHA; I suppressed
it in `.checkov.yaml` because "v1.0.0 to v1.1.0" is readable in a diff and a
SHA is not.

## Security groups

Every rule is its own resource, keyed by name:

```hcl
ingress_rules = {
  "https-from-office-lisbon" = { ip_protocol = "tcp", from_port = 443, to_port = 443, cidr_ipv4 = "203.0.113.10/32", description = "..." }
  "https-from-office-porto"  = { ip_protocol = "tcp", from_port = 443, to_port = 443, cidr_ipv4 = "198.51.100.7/32",  description = "..." }
}
```

Remove the Porto entry and the plan is one line:

```
# module.web_sg.aws_vpc_security_group_ingress_rule.this["https-from-office-porto"] will be destroyed

Plan: 0 to add, 0 to change, 1 to destroy.
```

I checked this instead of assuming it: two plans against a real account
differing only in the allow-list, with the rule addresses pulled from each and
diffed. One address appeared and none moved.

Inline `ingress` blocks rewrite the whole attribute. `count` over a list shifts
every index after the one you remove, so taking out one rule churns three.

## Running the checks

```bash
terraform fmt -check -recursive

for dir in task1-terraform-module task1-terraform-module/bootstrap \
           task2-aws-security task3-lambda-troubleshooting/terraform; do
  terraform -chdir="$dir" init -backend=false -input=false
  TF_WORKSPACE=staging terraform -chdir="$dir" validate
done

for dir in modules/*/; do
  terraform -chdir="$dir" init -backend=false -input=false
  terraform -chdir="$dir" validate
done

TF_WORKSPACE=staging tflint --recursive --minimum-failure-severity=warning
checkov

cd task3-lambda-troubleshooting
python3 -m venv .venv && . .venv/bin/activate
pip install -r tests/requirements.txt
pytest tests
```

`TF_WORKSPACE` is there because task 1 has no settings for the `default`
workspace. `init` on a root pulls the modules from the tag and needs network
access. All of it passes, and CI runs the same on every pull request.

Install checkov with pip, not Homebrew. The Homebrew build runs a smaller set
of checks, which is why the workflow pins `checkov==3.3.20` from pip.

`scripts/check-suppressions.py` fails if a `checkov:skip` comment never fires.
A suppression on the wrong resource is silent: the finding comes back while
the comment next to it claims it was handled. CI runs this after checkov.

You need Terraform 1.9+, and Python 3.12+ for the task 3 tests. AWS credentials
only if you want to apply.

## Assumptions

I did not apply any of this. The three configurations plan cleanly against a
real account (33, 110 and 13 resources) and the tests pass, but nothing was
created.

Region is `eu-west-1`, except task 3, which stays on `us-east-1` because its
brief says not to touch the provider block.

The root user cannot be disabled through Terraform or any AWS API, so task 2
does the part that can: Config rules for root MFA and root access keys, and an
alarm on any root activity.

The repository task 3 links to no longer exists. I recovered the original
broken files from the first commit of a public copy and kept them in
`task3-lambda-troubleshooting/original/`; `FIXES.md` says how to verify that.
