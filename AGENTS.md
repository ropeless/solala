## Review workflow

For reviews with Barry, rank recommendations by bang-for-buck. Put small changes with substantial benefits first.

For each batch of issues from a review, first list the issues by number and headline.

Subsequently, present one recommendation at a time.
Number each issue in its headline as X of Y, where X is its position in the batch and Y
is the total number of issues in that batch. Include a headline, the issue, and the recommended solution.
Keep each issue report to one page of text or less.
End each issue if there is a single recommendation, report with **Approve · Reject · Discuss**.
If there are multiple recommendations, number (i), (ii), (iii) etc, and report with
**Approve (i) · Approve (ii) · Approve (iii) · Reject · Discuss**.

- Approve: Apply and verify the agreed edit, then present the next issue.
- Reject: Present the next issue without editing.
- Discuss: Work through Barry's feedback and revise the recommendation. Wait for approval before editing.

## Python style

Follow the conventions in [doc/python-style.md](doc/python-style.md) when  editing Python code in this project.

## Testing

Follow the [testing protocol](doc/testing-protocol.md) when writing or  updating unit tests.

## PyCharm inspections

Check PyCharm's inspection results after changing Python code, including warnings
and weak warnings. Fix straightforward errors and warnings directly, then rerun
the inspection. Ask Barry for approval before proceeding if an attempted fix
leaves a finding unresolved, introduces another finding, or requires refactoring.
