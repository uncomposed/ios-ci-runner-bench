# iOS CI runner bench

How long does a mid-sized SwiftUI app take to build and test on GitHub's standard hosted runners, compared with a developer laptop?

This repo answers that for one project shape. `bench/generate.py` writes a synthetic Swift package and iOS 26 app. They're the same size and structure as a real app, about 240k lines in all:

| Area | Files | Lines |
|---|---|---|
| Swift package, 8 modules | 280 | ~64k |
| Package tests (XCTest) | 352 | ~91k |
| SwiftUI app | 181 | ~52k |
| App unit tests | 73 | ~33k |
| UI test | 1 | – |

The code means nothing, but the compiler has to do real work on it. It has Codable and Hashable value types, enums with associated values, generics, actors, cross-module calls, SwiftUI views with `@Observable` models, and tests that really run. Generation is deterministic, so every machine builds the same thing.

`bench/run.py` times each phase and samples memory pressure and swap while it runs:

1. Package: clean build of tests, then the test run (macOS and Linux)
2. App: clean simulator `build-for-testing`
3. App: incremental rebuild after a one-line edit in the lowest module
4. App: device build without signing
5. Simulator boot, app unit tests, one UI test

## Running it

On GitHub: **Actions → Runner benchmark → Run workflow**. It runs only when started by hand, with no schedule and no push trigger. It uses only the standard runners: `ubuntu-latest`, `macos-26` and the `xcode-27` preview image. The optional concurrency test runs 5 macOS jobs at once, the free-plan limit, to show the slowdown.

Locally:

```sh
python3 bench/generate.py
(cd generated && xcodegen generate)
python3 bench/run.py --label my-laptop
python3 bench/summarize.py results
```

## What this does not show

- **Your app's real timings.** Real projects have resources, binary frameworks, build scripts and slower tests (database, audio, network fakes). The synthetic tests run fast, so the package-test phase is almost all compile time. Use the hosted-to-laptop **ratio** on this workload, then apply it to your own measured laptop times.
- **Flakiness**, signing, archiving or upload.
- **Caching.** Every run starts clean on purpose.

## Results

Results are posted to each workflow run's summary.

## Licence

MIT
