import Foundation
import os

/// Signpost intervals for the tap-lag work (Instruments > os_signpost, category "perf"). Free when nobody is recording.
enum PerfSignpost {
    struct Interval { let name: StaticString; let state: OSSignpostIntervalState }
    private static let signposter = OSSignposter(subsystem: Bundle.main.bundleIdentifier ?? "io.severin.orch", category: "perf")
    static func begin(_ name: StaticString) -> Interval {
        Interval(name: name, state: signposter.beginInterval(name, id: signposter.makeSignpostID()))
    }
    static func end(_ i: Interval) { signposter.endInterval(i.name, i.state) }
}
