#!/usr/bin/env python3
"""Generate a synthetic Swift package and iOS app shaped like a mid-sized SwiftUI project.

The shape (file counts and line counts per area) is set by SHAPE below. The code is meaningless but
realistic for the compiler: Codable/Hashable value types, enums with associated values, protocols and
generics, actors, cross-module references, SwiftUI views with @Observable models, and XCTest suites
that really run. Output is deterministic, so every runner builds the same thing.

Usage: python3 bench/generate.py [--out generated] [--scale 1.0]
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

# Files and approximate lines per file for each area.
SHAPE = {
    'modules': 8,
    'package_files_per_module': 35,   # 280 files
    'package_lines_per_file': 218,    # ~61k lines
    'test_files_per_module': 44,      # 352 files
    'test_lines_per_file': 240,       # ~85k lines
    'app_files': 180,
    'app_lines_per_file': 268,        # ~48k lines
    'app_test_files': 73,
    'app_test_lines_per_file': 443,   # ~32k lines
}


def mod(i: int) -> str:
    return f'BenchKit{i}'


def package_source(i: int, j: int, lines: int) -> str:
    deps = '' if i == 0 else f'import {mod(0)}\n'
    t = f'{i}_{j}'
    head = f'''import Foundation
{deps}
public enum Kind{t}: Codable, Hashable, Sendable {{
    case plain
    case weighted(Double)
    case labelled(String, Int)

    public var weight: Double {{
        switch self {{
        case .plain: return 1
        case .weighted(let value): return value
        case .labelled(let label, let count): return Double(label.count + count) / 4
        }}
    }}
}}

public struct Record{t}: Codable, Hashable, Sendable, Identifiable {{
    public var id: Int
    public var title: String
    public var score: Double
    public var tags: [String]
    public var kind: Kind{t}

    public init(id: Int, title: String, score: Double, tags: [String], kind: Kind{t}) {{
        self.id = id
        self.title = title
        self.score = score
        self.tags = tags
        self.kind = kind
    }}

    public static func sample(_ count: Int) -> [Record{t}] {{
        (0..<count).map {{ index in
            Record{t}(
                id: index,
                title: "Item \\(index) of {t}",
                score: Double((index * 37) % 101) / 10,
                tags: index.isMultiple(of: 3) ? ["a", "b"] : ["c"],
                kind: index.isMultiple(of: 2) ? .weighted(Double(index % 7)) : .labelled("L\\(index)", index % 5)
            )
        }}
    }}
}}

public protocol Scoring{t}: Sendable {{
    func score(_ record: Record{t}) -> Double
}}

public func rank{t}<S: Scoring{t}>(_ records: [Record{t}], by scorer: S) -> [Record{t}] {{
    records.sorted {{ lhs, rhs in
        let left = scorer.score(lhs)
        let right = scorer.score(rhs)
        return left == right ? lhs.id < rhs.id : left > right
    }}
}}

public actor Store{t} {{
    private var items: [Int: Record{t}] = [:]

    public init() {{}}

    public func put(_ record: Record{t}) {{
        items[record.id] = record
    }}

    public func get(_ id: Int) -> Record{t}? {{
        items[id]
    }}

    public func summary() -> Double {{
        items.values.reduce(0) {{ $0 + $1.score * $1.kind.weight }}
    }}
}}
'''
    if i > 0:
        other = f'{0}_{j % SHAPE["package_files_per_module"]}'
        head += f'''
public func bridge{t}(_ records: [Record{other}]) -> [Record{t}] {{
    records.map {{ Record{t}(id: $0.id, title: $0.title, score: $0.score, tags: $0.tags, kind: .weighted($0.kind.weight)) }}
}}
'''
    blocks = []
    k = 0
    while (head.count('\n') + sum(b.count('\n') for b in blocks)) < lines:
        blocks.append(f'''
public struct Scorer{t}_{k}: Scoring{t} {{
    public let bias: Double
    public let tagBonus: [String: Double]

    public init(bias: Double = {k}.5, tagBonus: [String: Double] = ["a": {k + 1}, "c": 0.5]) {{
        self.bias = bias
        self.tagBonus = tagBonus
    }}

    public func score(_ record: Record{t}) -> Double {{
        let tags = record.tags.compactMap {{ tagBonus[$0] }}.reduce(0, +)
        return (record.score + bias) * record.kind.weight + tags
    }}
}}
''')
        k += 1
    return head + ''.join(blocks)


def package_test(i: int, j: int, lines: int) -> str:
    src = j % SHAPE['package_files_per_module']
    t = f'{i}_{src}'
    head = f'''import XCTest
import Foundation
@testable import {mod(i)}

final class Suite{i}_{j}Tests: XCTestCase {{
'''
    tests = []
    k = 0
    while (head.count('\n') + sum(b.count('\n') for b in tests)) < lines - 2:
        tests.append(f'''
    func testRankAndRoundTrip{k}() throws {{
        let records = Record{t}.sample({20 + k})
        let ranked = rank{t}(records, by: Scorer{t}_0(bias: {k}))
        XCTAssertEqual(ranked.count, records.count)
        let data = try JSONEncoder().encode(ranked)
        let decoded = try JSONDecoder().decode([Record{t}].self, from: data)
        XCTAssertEqual(decoded, ranked)
        XCTAssertEqual(Set(decoded.map(\\.id)), Set(records.map(\\.id)))
    }}

    func testStoreSummary{k}() async {{
        let store = Store{t}()
        for record in Record{t}.sample({10 + k}) {{
            await store.put(record)
        }}
        let summary = await store.summary()
        XCTAssertGreaterThanOrEqual(summary, 0)
        let first = await store.get(0)
        XCTAssertNotNil(first)
    }}
''')
        k += 1
    return head + ''.join(tests) + '}\n'


def package_manifest() -> str:
    n = SHAPE['modules']
    products = ',\n'.join(f'        .library(name: "{mod(i)}", targets: ["{mod(i)}"])' for i in range(n))
    targets = []
    for i in range(n):
        deps = '' if i == 0 else f'"{mod(0)}"'
        targets.append(f'        .target(name: "{mod(i)}", dependencies: [{deps}])')
        targets.append(f'        .testTarget(name: "{mod(i)}Tests", dependencies: ["{mod(i)}"])')
    target_list = ',\n'.join(targets)
    return f'''// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "BenchKit",
    platforms: [.iOS("26.0"), .macOS(.v15)],
    products: [
{products}
    ],
    targets: [
{target_list}
    ]
)
'''


def app_source(n: int, lines: int) -> str:
    i = n % SHAPE['modules']
    j = n % SHAPE['package_files_per_module']
    t = f'{i}_{j}'
    head = f'''import SwiftUI
import Observation
import {mod(i)}

@Observable
@MainActor
final class ScreenModel{n} {{
    var items: [Record{t}] = Record{t}.sample(40)
    var filter = ""
    var showWeighted = true
    var selection: Int?

    var visible: [Record{t}] {{
        let ranked = rank{t}(items, by: Scorer{t}_0())
        return ranked.filter {{ record in
            (filter.isEmpty || record.title.localizedCaseInsensitiveContains(filter))
                && (showWeighted || record.kind.weight <= 1)
        }}
    }}

    func toggle() {{
        showWeighted.toggle()
    }}
}}

struct Screen{n}View: View {{
    @State private var model = ScreenModel{n}()

    var body: some View {{
        List {{
            Section("Ranked") {{
                ForEach(model.visible) {{ record in
                    Row{n}_0(record: record, selected: model.selection == record.id)
                        .onTapGesture {{ model.selection = record.id }}
                }}
            }}
            Section("Options") {{
                Toggle("Weighted", isOn: $model.showWeighted)
                Button("Toggle") {{ model.toggle() }}
            }}
        }}
        .searchable(text: $model.filter)
        .navigationTitle("Screen {n}")
        .accessibilityIdentifier("screen-{n}")
    }}
}}
'''
    rows = []
    k = 0
    while (head.count('\n') + sum(b.count('\n') for b in rows)) < lines:
        rows.append(f'''
struct Row{n}_{k}: View {{
    let record: Record{t}
    let selected: Bool

    var body: some View {{
        HStack(alignment: .firstTextBaseline, spacing: 12) {{
            VStack(alignment: .leading, spacing: 4) {{
                Text(record.title)
                    .font(.headline)
                    .foregroundStyle(selected ? Color.accentColor : Color.primary)
                Text(record.tags.joined(separator: ", "))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }}
            Spacer()
            Text(record.score, format: .number.precision(.fractionLength(1)))
                .monospacedDigit()
            Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                .accessibilityLabel(selected ? "Selected" : "Not selected")
        }}
        .padding(.vertical, {k % 6 + 2})
    }}
}}
''')
        k += 1
    return head + ''.join(rows)


def app_main(count: int) -> str:
    links = '\n'.join(
        f'                    NavigationLink("Screen {n}") {{ Screen{n}View() }}' for n in range(count))
    return f'''import SwiftUI

@main
struct BenchApp: App {{
    var body: some Scene {{
        WindowGroup {{
            RootView()
        }}
    }}
}}

struct RootView: View {{
    var body: some View {{
        TabView {{
            NavigationStack {{ Screen0View() }}
                .tabItem {{ Label("First", systemImage: "1.circle") }}
            NavigationStack {{
                List {{
{links}
                }}
                .navigationTitle("All screens")
            }}
            .tabItem {{ Label("All", systemImage: "list.bullet") }}
        }}
    }}
}}
'''


def app_test(n: int, lines: int) -> str:
    screens = SHAPE['app_files']
    head = f'''import XCTest
@testable import BenchApp

@MainActor
final class AppSuite{n}Tests: XCTestCase {{
'''
    tests = []
    k = 0
    while (head.count('\n') + sum(b.count('\n') for b in tests)) < lines - 2:
        s = (n * 7 + k) % screens
        tests.append(f'''
    func testFilterAndToggle{k}() {{
        let model = ScreenModel{s}()
        let all = model.visible.count
        XCTAssertGreaterThan(all, 0)
        model.filter = "Item 1"
        XCTAssertLessThanOrEqual(model.visible.count, all)
        model.filter = ""
        model.toggle()
        XCTAssertLessThanOrEqual(model.visible.count, all)
        model.toggle()
        XCTAssertEqual(model.visible.count, all)
    }}
''')
        k += 1
    return head + ''.join(tests) + '}\n'


UI_TEST = '''import XCTest

final class BenchAppUITests: XCTestCase {
    @MainActor
    func testOpenAScreenFromTheList() throws {
        let app = XCUIApplication()
        app.launch()
        app.tabBars.buttons["All"].tap()
        app.buttons["Screen 3"].tap()
        XCTAssertTrue(app.navigationBars["Screen 3"].waitForExistence(timeout: 10))
    }
}
'''


def project_yml() -> str:
    deps = '\n'.join(f'      - package: BenchKit\n        product: {mod(i)}' for i in range(SHAPE['modules']))
    return f'''name: BenchApp
options:
  bundleIdPrefix: io.github.bench
  deploymentTarget:
    iOS: "26.0"
packages:
  BenchKit:
    path: Package
settings:
  base:
    SWIFT_VERSION: "6.0"
    GENERATE_INFOPLIST_FILE: YES
    CODE_SIGN_STYLE: Automatic
    DEVELOPMENT_TEAM: ""
targets:
  BenchApp:
    type: application
    platform: iOS
    sources:
      - path: App
    info:
      path: App/Info.plist
      properties:
        UILaunchScreen: {{}}
    dependencies:
{deps}
  BenchAppTests:
    type: bundle.unit-test
    platform: iOS
    sources:
      - path: AppTests
    dependencies:
      - target: BenchApp
  BenchAppUITests:
    type: bundle.ui-testing
    platform: iOS
    sources:
      - path: AppUITests
    dependencies:
      - target: BenchApp
schemes:
  BenchApp:
    build:
      targets:
        BenchApp: all
        BenchAppTests: [test]
        BenchAppUITests: [test]
    test:
      targets:
        - BenchAppTests
        - BenchAppUITests
'''


def write(path: Path, text: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return text.count('\n')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='generated')
    parser.add_argument('--scale', type=float, default=1.0, help='multiply file counts (for quick local checks)')
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    for key in ('package_files_per_module', 'test_files_per_module', 'app_files', 'app_test_files'):
        SHAPE[key] = max(4, round(SHAPE[key] * args.scale))

    totals = {'package': [0, 0], 'package tests': [0, 0], 'app': [0, 0], 'app tests': [0, 0]}

    def add(area: str, lines: int) -> None:
        totals[area][0] += 1
        totals[area][1] += lines

    write(out / 'Package/Package.swift', package_manifest())
    for i in range(SHAPE['modules']):
        for j in range(SHAPE['package_files_per_module']):
            add('package', write(out / f'Package/Sources/{mod(i)}/File{j}.swift',
                                 package_source(i, j, SHAPE['package_lines_per_file'])))
        for j in range(SHAPE['test_files_per_module']):
            add('package tests', write(out / f'Package/Tests/{mod(i)}Tests/Suite{j}Tests.swift',
                                       package_test(i, j, SHAPE['test_lines_per_file'])))
    for n in range(SHAPE['app_files']):
        add('app', write(out / f'App/Screen{n}.swift', app_source(n, SHAPE['app_lines_per_file'])))
    add('app', write(out / 'App/BenchApp.swift', app_main(SHAPE['app_files'])))
    for n in range(SHAPE['app_test_files']):
        add('app tests', write(out / f'AppTests/AppSuite{n}Tests.swift',
                               app_test(n, SHAPE['app_test_lines_per_file'])))
    write(out / 'AppUITests/BenchAppUITests.swift', UI_TEST)
    write(out / 'project.yml', project_yml())
    for area, (files, lines) in totals.items():
        print(f'{area:14} {files:4} files {lines:7} lines')


if __name__ == '__main__':
    main()
