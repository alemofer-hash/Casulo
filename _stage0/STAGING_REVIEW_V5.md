# Stage Zero staging review v5

Canonical root: `C:\Users\guimo\Downloads\ex`

## Base proposal

- proposed files: 31,543
- proposed bytes: 924,921,445
- ignored files: 157,392
- ignored bytes: 18,634,386,044
- proposed files above 100 MiB: 0
- proposal CSV SHA-256: `0dcd3e48c42867ab2969043841054df1ddfba9f2563a952695cce685d047e9fb`
- proposal summary SHA-256 before copying: `d679f98bddc7185b68a903c046dc56760450eb19a8a95b67dc3c28bbfa91e0dd`

Four additive evidence files are staged after the base proposal: this report,
the proposal summary JSON, and the two verified nested-history bundles. The
expected final staged file count is therefore 31,547.

## Nested Git histories

- `nested-casulo-history.bundle`: verified, SHA-256 `9adf11460613d83ba73bfc28a1eb514e0aa8288228f7576f62365c9472cc34cd`
- `nested-bootloader-history.bundle`: verified, SHA-256 `7083553e1264e58457368d04ad1c1135516826f12bc5513957473fee18dd1966`

The root snapshot stages current working files as ordinary blobs and excludes
all nested `.git` metadata. The bundles preserve the prior nested histories.

## Raw-byte policy and recovery

The root index was created with `git hash-object --no-filters` so committed
blobs preserve working-file bytes. During Stage Zero, the local file
`.git/info/attributes` contains:

```text
* -text -filter -working-tree-encoding
```

Its SHA-256 is
`154dfec50117bc3f53309bd29b2d24ef50948110b57446a2792a2f47bc51e9c6`.
Git bundles do not include `.git/info/attributes`. For a byte-preserving
restore, clone with `--no-checkout`, recreate the line above in the new
repository's `.git/info/attributes`, and only then check out the Stage Zero
tag. `git archive` or `git cat-file` also yields the committed blob bytes.

## Review gate

No root commit or root tag existed when this review report was created.
