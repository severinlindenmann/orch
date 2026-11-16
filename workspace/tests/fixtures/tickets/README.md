# Ticket fixtures (R8.2)

Each folder `<date>-<sha>/` holds the `.orch/` ticket files an OLDER orch version wrote with its own CLI.
`workspace/tests/test_ticket_fixtures.py` runs the current code on every folder here (new folders are picked up
automatically): list, show, edit, save, evidence write, and checks that no field is lost.

Contents of a folder: `.orch/tickets/*.json` (4 tickets: checklist with evidence of types command, note, url, pr,
file; a question with options and an answer slot; a done-when part; waiting until a time and on an external
reference; a sub-ticket; a ticket in Review; `ext` data of an add-on), `.orch/ticket-counter.json`,
`.orch/config.toml`, and the copied evidence file. Only test data. Proof fields of the old
human-proof code are added by the test itself (`_plant_unknown`), because the CLI of these versions cannot
produce a finished (done) ticket without a person.

## Add a folder for a new version

```sh
git worktree add --detach /path/to/old <sha>          # the version to freeze
H=$(mktemp -d ~/orch-dev/.t797a-XXXX)                 # isolated HOME
workspace/tests/fixtures/tickets/make_fixture.sh /path/to/old $H   # runs `orch` of that version under env -i
D=workspace/tests/fixtures/tickets/<date>-<sha>
mkdir -p $D/.orch && cp -R $H/ws/.orch/tickets $H/ws/.orch/ticket-counter.json $H/ws/.orch/config.toml $D/.orch/
git worktree remove /path/to/old; rm -r "$H"          # delete exactly those paths
```

The commands of `make_fixture.sh` may need small changes for another version (a flag renamed); edit the copy
you run, not the fixtures already committed. Fixtures made: 2026-11-09 (99e09754), 2026-11-12 (74bf19ea),
2026-11-14 (602bd79d).
