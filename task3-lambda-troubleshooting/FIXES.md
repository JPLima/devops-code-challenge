# Changes

Eight defects. The unmodified originals are in [`original/`](original/); the
README says where they came from and how to verify that.

| # | Defect | Symptom |
|---|---|---|
| 1 | Hardcoded bucket name | `apply` fails: `BucketAlreadyExists` |
| 2 | `acl` on `aws_s3_bucket` | `validate` fails: unsupported argument |
| 3 | Lambda points at an object nothing uploads | `apply` fails: key not found |
| 4 | IAM role with no permissions | Runs, writes no logs, fails invisibly |
| 5 | No `source_code_hash` | Code changes uploaded but never deployed |
| 6 | `python3.8` runtime | `apply` fails: runtime not accepted |
| 7 | No `required_providers` | Makes defect 2 fatal |
| 8 | Bucket unhardened, handler never touches S3 | Nothing proves it works |

## 1. The bucket name is hardcoded

```hcl
bucket = "my-super-cool-bucket"
```

S3 names are one global namespace shared by every AWS account, so this was
taken long before the challenge was written. Added a random suffix with the
prefix as a variable:

```hcl
resource "random_id" "bucket_suffix" {
  byte_length = 4
}

bucket = "${var.bucket_prefix}-${random_id.bucket_suffix.hex}"
```

`random_id` keeps its value in state, so the name is generated once and does
not change on later applies.

## 2. `acl` was removed from `aws_s3_bucket`

```hcl
acl = "private"
```

Deprecated in AWS provider v4 and removed from this resource in v5. With a
current provider the configuration does not parse. Nothing pinned the provider
(defect 7).

I dropped it rather than adding an `aws_s3_bucket_acl`. `BucketOwnerEnforced`
disables ACLs entirely, which is stricter and cannot be undone by a stray
`PutObjectAcl`:

```hcl
resource "aws_s3_bucket_ownership_controls" "my_bucket" {
  bucket = aws_s3_bucket.my_bucket.id
  rule { object_ownership = "BucketOwnerEnforced" }
}
```

## 3. The Lambda points at an object nothing creates

```hcl
s3_key = "lambda_function_payload.zip"
```

Two problems in one line. Nothing builds or uploads that zip, and because the
key is a literal rather than a reference, Terraform sees no dependency between
the function and the object.

```hcl
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.module}/.build/lambda_function_payload.zip"
}

resource "aws_s3_object" "lambda_zip" {
  bucket = aws_s3_bucket.my_bucket.id
  key    = "lambda_function_payload.zip"
  source = data.archive_file.lambda.output_path
  etag   = data.archive_file.lambda.output_md5
}

resource "aws_lambda_function" "my_lambda" {
  s3_key = aws_s3_object.lambda_zip.key
}
```

`archive_file` is a data source. The zip is built at plan time from source and
nothing binary is committed. `etag` is what makes S3 replace the object when
the zip changes. Referencing `aws_s3_object.lambda_zip.key` creates the
ordering the original lacked.

The original also used `aws_s3_bucket_object`, removed in provider v5.
`aws_s3_object` is the current name.

## 4. The execution role has no permissions

```hcl
resource "aws_iam_role" "iam_for_lambda" {
  assume_role_policy = jsonencode({ ... })
}
```

A trust policy says who may assume the role. It grants nothing. With nothing
attached the function cannot even create its own log stream and every failure
is silent. This is the defect that hides the other seven.

```hcl
statement {
  sid       = "WriteOwnLogs"
  actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
  resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
}

statement {
  sid       = "ReadWriteInvocationRecords"
  actions   = ["s3:PutObject", "s3:GetObject"]
  resources = ["${aws_s3_bucket.my_bucket.arn}/invocations/*"]
}
```

Not `AWSLambdaBasicExecutionRole`, which grants `logs:CreateLogGroup` on `*`
and lets the function write into any log group in the account.

The log group is created explicitly too. One that Lambda creates on first
invocation has no retention and cannot be named in an IAM policy at plan time,
because it does not exist yet.

## 5. Code changes are uploaded but never deployed

Edit `handler.py`, apply, and the new zip reaches S3 while the deployed
function keeps running the old code, with nothing in the plan to explain it.
Lambda does not watch the S3 object:

```hcl
source_code_hash = data.archive_file.lambda.output_base64sha256
```

This is the idempotency problem in the direction people miss. The original was
too idempotent: it ignored a change it should have acted on.

## 6. The runtime is past end of support

```hcl
runtime = "python3.8"
```

Python 3.8 reached end of support in October 2024 and AWS refuses to create new
functions on it. Moved to `python3.12`, as a variable so the next bump is one
line.

## 7. Nothing pinned the provider version

The original has no `terraform` block at all. `init` resolves whatever is
current, which is why defect 2 and the `aws_s3_bucket_object` rename in defect
3 became fatal: both were valid when written and removed in v5.

Added a `versions.tf` pinning Terraform and the three providers.

On the constraint: the challenge says not to change the provider settings. The
`provider "aws"` block is untouched, same region and all:

```hcl
provider "aws" {
  region = "us-east-1"
}
```

`versions.tf` adds version constraints that were absent. If a reviewer reads
the constraint as covering that too, then defect 2 can only be fixed by
matching whatever provider the grader happens to resolve.

## 8. Nothing demonstrated the success criteria

The criteria are that the Lambda executes successfully and performs its task,
and that the bucket is correctly configured and accessible from it. The
original handler:

```python
def handler(event, context):
    return {'statusCode': 200, 'body': json.dumps('Hello from Lambda!')}
```

It returns 200 whether or not the bucket exists and whether or not the role has
permissions. It never touches S3, and the bucket had no encryption, versioning
or public access block.

The handler now writes a record of the invocation and reads it back:

```python
client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
roundtrip = client.get_object(Bucket=bucket, Key=key)["Body"].read()
```

Errors are logged with the S3 error code and re-raised, so a failure appears in
CloudWatch as a reason instead of a 200. The bucket name comes from an
environment variable read at call time, so a missing variable raises a
`RuntimeError` naming it rather than an opaque `Runtime.ImportModuleError`.

The bucket got versioning, SSE-S3 encryption, public access blocked, ACLs
disabled, a policy denying non-TLS requests, and a lifecycle rule expiring
invocation records after 90 days.

Eight tests in `tests/` cover the round trip, the key layout, the failure modes
and the client caching.

## Other changes

No symptom forced these:

- `timeout = 30` and `memory_size = 256`. The defaults of 3 seconds and 128 MB
  are tight for two S3 round trips on a cold start.
- `reserved_concurrent_executions = 10`, so a runaway trigger cannot consume
  the account's whole concurrency pool.
- `force_destroy = true` on the bucket, so `destroy` works without emptying it
  by hand. Right for a challenge, wrong for production.
- An explicit CloudWatch log group, as above.

## What I did not add

The constraint is no new AWS services. The original used three: S3, Lambda and
IAM.

No KMS. The bucket uses SSE-S3 rather than a customer-managed key. A CMK would
be better and it is what tasks 1 and 2 do, but the original had no encryption
block at all. KMS would be a new service here. Three checkov checks are
suppressed for this, each citing the constraint inline: `CKV_AWS_145` (SSE-KMS
on the bucket), `CKV_AWS_158` (CMK on the log group) and `CKV_AWS_173` (CMK on
the function's environment variables). Lambda already encrypts environment
variables with an AWS-managed key; the last one is about auditability.

No dead letter queue (`CKV_AWS_116`), which needs SQS or SNS. The function is
invoked synchronously anyway, where the caller receives the error.

Both would be right the day the constraint is lifted.
