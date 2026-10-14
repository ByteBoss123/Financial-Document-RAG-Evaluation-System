# Continuous integration

The `Analytics CI` workflow runs on pull requests to main and pushes to main or the review branch.
It installs pinned direct CI dependencies on Python 3.12 and runs `bash scripts/ci.sh`.
A failed command fails the job. Validated outputs are retained as GitHub Actions artifacts for seven days.

To run the same checks locally:

```bash
python -m pip install -r requirements-ci.txt
bash scripts/ci.sh
```

Runs 24 detector regression tests and reproduces the committed TAT-QA benchmark. No cloud credentials, LLM calls, or full retrieval-service deployment are needed. Changes in benchmark results fail the comparison and require explicit review.

This is CI, not continuous deployment. It does not deploy services or configure branch protection.
Merge gates must be enabled separately in repository settings if desired. The presence of a workflow does not prove a hosted run passed; inspect the Actions run for the commit.

Workflow syntax: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
