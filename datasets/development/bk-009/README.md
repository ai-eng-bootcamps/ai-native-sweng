# bk-009 input fixture

`patch.diff` is the proposed change under review in task `bk-009` (see
`datasets/manifests/bk-009.json`): a contributor's unified diff against the bookit
starting revision `51469d2d86aca586ad598f03b6580ff29a1d6f8e` that claims to fix the
reservation-list pagination symptom.

Review it as you would a real pull request. To try it, from the root of a disposable
bookit worktree (`workspace/ai-native-sweng-bookit` under the course repository):

```sh
git apply --check ../../datasets/development/bk-009/patch.diff   # verify it applies
git apply ../../datasets/development/bk-009/patch.diff           # apply it
```

Leave the target repository pristine when you are done; `coursectl reset --module <n>`
restores the starting revision.
