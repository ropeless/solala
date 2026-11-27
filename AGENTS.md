## Review workflow

For reviews with the developer, rank recommendations by bang-for-buck. Put small changes with substantial benefits first.

For each batch of issues from a review, first list the issues by number and headline.

Subsequently, present one issue at a time.
Number each issue in its headline as X of Y, where X is its position in the batch and Y
is the total number of issues in that batch. Include a headline, the issue, and the recommended solution.
Keep each issue report to one page of text or less.

At the bottom of each issue provide a prompt.
If there is only one recommendation, prompt with **Approve**, **Reject**, and **Discuss**.
For multiple recommendations, number the recommendation (i), (ii), etc. and
provide a separate approval choice for each, such as **Approve (i) · Approve (ii) · Reject · Discuss**.

## Python style

Follow the conventions in [docs/python-style.md](docs/python-style.md) when editing Python code in this project.

## Testing

Follow the [testing protocol](docs/testing-protocol.md) when writing or updating unit tests.

## Project design decisions

Consult the [architecture guide](docs/architecture.md) and the relevant
topic-specific documentation in [docs/](docs/) before changing an existing
design decision. Record new or revised decisions in the existing document
that covers the affected area.

## PyCharm inspections

Check PyCharm's inspection results after changing Python code, including warnings
and weak warnings. Fix straightforward errors and warnings directly, then rerun
the inspection. Ask the developer for approval before proceeding if an attempted fix
leaves a finding unresolved, introduces another finding, or requires refactoring.
