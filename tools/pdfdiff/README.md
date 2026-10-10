# Sheet diffs for pull requests

When a pull request is built, every sheet (`output/*.pdf`) is compared
with the published survey, and the PR gets a comment showing what
changed:

- an overview of each changed sheet: **red** is what was removed,
  **blue** what was added, and pale grey everything unchanged, with the
  changed areas boxed and numbered
- a close-up of each numbered area, next to how it now looks

Shifts of a pixel or so are ignored, so a sheet that is redrawn a hair
to one side doesn't light up everywhere. When a sheet changes size,
usually because the drawing has grown, the two versions are lined up on
the drawing first, so the header and legend may show as moved.

To run it yourself, after a build:

```bash
pip install numpy pillow      # and poppler-utils, for pdftoppm
python3 -m tools.pdfdiff --base https://cavesurveying.github.io/uk_mendips_swildons-hole/ --head output --out pr-diff
```

`--base` can also be a folder of PDFs, for example an earlier build's
`output/`.

## How the comment gets posted

`build.yml` runs the PR's own code, so it has no write access, and none
at all for a PR from a fork. It makes the pictures and uploads them.
`pr-comment.yml` then runs from `main`, checks that the PR's head is
the commit that was built, pushes the pictures to the `pr-previews`
branch (GitHub won't show images from a build's artifacts in a
comment), and posts or updates the comment. `pr-previews` only ever
holds the latest pictures for each open PR, and is rewritten every
time. Changes to `pr-comment.yml` only take effect once they're on
`main`.
