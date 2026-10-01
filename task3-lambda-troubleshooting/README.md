# Task 3: Lambda and Terraform troubleshooting

A broken Terraform and Lambda project, diagnosed and fixed.

[FIXES.md](FIXES.md) is the writeup: eight defects, with the original code, the
symptom, the cause and the change for each.

```
task3-lambda-troubleshooting/
├── FIXES.md
├── original/     the broken files, unmodified
├── terraform/
├── lambda/
└── tests/
```

## Where the original came from

The repository the challenge links to,
`github.com/spinbet/devops-aws-lambda-troubleshooting-files`, no longer
resolves. A public copy at `github.com/jayeroll/devops-aws-lambda-troubleshooting-files`
has the original upload as its first commit, `e17c075`, before that author's
own fixes landed. `original/` is that commit, untouched:

```bash
git clone https://github.com/jayeroll/devops-aws-lambda-troubleshooting-files
git -C devops-aws-lambda-troubleshooting-files show e17c075:main.tf
```

The challenge document shows a `terraform/` and `lambda/` tree; the actual
repository is flat, so I restructured it to match the document.

## The defects

| # | Defect | Symptom |
|---|---|---|
| 1 | Hardcoded S3 bucket name | `apply` fails: `BucketAlreadyExists` |
| 2 | `acl` on `aws_s3_bucket` | `validate` fails: unsupported argument |
| 3 | Lambda references an object nothing uploads | `apply` fails: key not found |
| 4 | IAM role with no permissions policy | Runs, writes no logs, fails invisibly |
| 5 | No `source_code_hash` | Code changes uploaded but never deployed |
| 6 | `python3.8` runtime | `apply` fails: runtime no longer accepted |
| 7 | No `required_providers` | Defect 2 becomes fatal; builds not reproducible |
| 8 | Bucket unhardened, handler never touches S3 | Nothing proves the success criteria |

Defects 1, 2, 3 and 6 stop the apply. Defect 4 is the one that hurts: the
apply succeeds, the function exists, and every failure after that is silent
because the role cannot write logs.

## Running it

Tests, no AWS account needed:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r tests/requirements.txt
pytest tests
```

Eight tests against [moto](https://github.com/getmoto/moto), which implements
the S3 API in process. They cover the handler and its error handling. They do
not prove the IAM policy is sufficient, because moto does not evaluate IAM;
that part is reviewed by hand in FIXES.md.

Static checks:

```bash
terraform -chdir=terraform fmt -check
terraform -chdir=terraform init -backend=false
terraform -chdir=terraform validate
```

Against a real account. The provider stays on `us-east-1`, since the challenge
says not to change it:

```bash
terraform -chdir=terraform apply
terraform -chdir=terraform output -raw invoke_command | sh
terraform -chdir=terraform output -raw verify_object_command | sh
```

The first prints the handler's response with `"roundtrip_ok": true`. The second
lists the object it wrote. Apply twice to confirm the plan comes back empty.

## What the handler does

It writes a JSON record of the invocation to
`invocations/YYYY/MM/DD/<uuid>.json` and reads it back. A successful
`PutObject` only proves write access; reading proves the object is where we
think it is and that the role can read it. Errors are logged with the S3 error
code and re-raised, so a failure shows up in CloudWatch with a reason.

The original returned `Hello from Lambda!` unconditionally, which cannot fail
and so cannot pass either.

## Constraints

| Constraint | How |
|---|---|
| Cannot change provider settings | The `provider "aws"` block is byte for byte unchanged. `versions.tf` adds the missing `required_providers`; defect 7 explains why I read that as a different thing. |
| Limited to the current AWS services | S3, Lambda and IAM, the three the original used, plus the CloudWatch log group the function already wrote to. No KMS. |
| All changes via code | Everything is in `terraform/` or `lambda/`. No console steps, no binary committed. |
