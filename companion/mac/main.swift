// orch Companion (ORCH-1195): a menu bar app that "records your calls for Meetings".
// Step 2 job: notice when a call app (Teams) uses the microphone and tell orch on this computer, through files in
// its own folder only (no network, no port). orch reads now.json; a workspace that wants calls renews a file in
// wanted/. With no fresh wanted file Companion does nothing ("inactive"). Design: ORCH-1265 companion-design.md.
//
//   orch-companion                      menu bar app
//   orch-companion --headless           same job, no menu bar (tests)
//   orch-companion --selftest           check the call state machine, exit 0 when all pass
//   orch-companion --diagnose [secs]    print every Core Audio process (pid, bundle id, mic input) each second
//   orch-companion --fake-input FILE    lines "<seconds> <bundle-id> on|off" instead of Core Audio (tests)
// ORCH_COMPANION_HOME overrides ~/Library/Application Support/orch Companion.

import AppKit
import CoreAudio
import Foundation

let fixedLine = "records your calls for Meetings"
let callApps: [String: String] = [
    "com.microsoft.teams2": "Teams",
    "com.microsoft.teams": "Teams",
]
let startAfter = 3.0  // seconds a call app must hold the microphone before it counts as a call
let endAfter = 8.0  // seconds without any call app on the microphone before the call ends (mute keeps it on)
let heartbeat = 15.0
let wantedFresh = 120.0
let wantedForget = 86400.0

// MARK: - call state machine (pure, tested by --selftest)

struct Detector {
    enum State: Equatable { case idle, call(app: String, since: Double) }
    var state: State = .idle
    var candidate: (app: String, since: Double)? = nil
    var lastActive: Double = 0

    /// One sample: which call app holds the microphone now (nil = none). Returns true when the state changed.
    mutating func step(now: Double, active: String?) -> Bool {
        switch state {
        case .idle:
            guard let app = active else { candidate = nil; return false }
            if candidate == nil || candidate!.app != app { candidate = (app, now) }
            if now - candidate!.since >= startAfter {
                state = .call(app: app, since: candidate!.since)
                lastActive = now
                candidate = nil
                return true
            }
            return false
        case .call:
            if active != nil { lastActive = now; return false }
            if now - lastActive >= endAfter { state = .idle; return true }
            return false
        }
    }
}

func selftest() -> Int32 {
    var failed = 0
    func run(_ name: String, _ samples: [(Double, String?)], _ want: [Bool], _ end: Detector.State) {
        var d = Detector()
        var got: [Bool] = []
        for (t, a) in samples { got.append(d.step(now: t, active: a)) }
        if got != want || d.state != end {
            failed += 1
            print("FAIL \(name): changes \(got) want \(want), state \(d.state) want \(end)")
        } else {
            print("ok   \(name)")
        }
    }
    let T = "Teams"
    run("starts after 3 s", [(0, T), (1, T), (2, T), (3, T)], [false, false, false, true], .call(app: T, since: 0))
    run("short blip is no call", [(0, T), (1, T), (2, nil), (3, nil)], [false, false, false, false], .idle)
    run("blip restarts the count", [(0, T), (2, nil), (3, T), (5, T), (6, T)], [false, false, false, false, true],
        .call(app: T, since: 3))
    run("short gap keeps the call", [(0, T), (3, T), (5, nil), (10, nil), (11, T), (18, nil)],
        [false, true, false, false, false, false], .call(app: T, since: 0))
    run("ends 8 s after the mic was last on", [(0, T), (3, T), (4, nil), (10, nil), (11, nil)],
        [false, true, false, false, true], .idle)
    run("idle stays idle", [(0, nil), (100, nil)], [false, false], .idle)
    print(failed == 0 ? "selftest passed" : "selftest FAILED: \(failed)")
    return failed == 0 ? 0 : 1
}

// MARK: - who holds the microphone

struct ProcessInfo2 { let pid: Int32; let bundle: String; let input: Bool }

func readProp<T>(_ obj: AudioObjectID, _ sel: AudioObjectPropertySelector, _ initial: T) -> T? {
    var addr = AudioObjectPropertyAddress(mSelector: sel, mScope: kAudioObjectPropertyScopeGlobal,
                                          mElement: kAudioObjectPropertyElementMain)
    var value = initial
    var size = UInt32(MemoryLayout<T>.size)
    let st = withUnsafeMutablePointer(to: &value) { AudioObjectGetPropertyData(obj, &addr, 0, nil, &size, $0) }
    return st == noErr ? value : nil
}

func audioProcesses() -> [ProcessInfo2] {
    var addr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyProcessObjectList,
                                          mScope: kAudioObjectPropertyScopeGlobal,
                                          mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    let sys = AudioObjectID(kAudioObjectSystemObject)
    guard AudioObjectGetPropertyDataSize(sys, &addr, 0, nil, &size) == noErr, size > 0 else { return [] }
    var ids = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    guard AudioObjectGetPropertyData(sys, &addr, 0, nil, &size, &ids) == noErr else { return [] }
    return ids.map { id in
        let pid: Int32 = readProp(id, kAudioProcessPropertyPID, Int32(-1)) ?? -1
        let input: UInt32 = readProp(id, kAudioProcessPropertyIsRunningInput, UInt32(0)) ?? 0
        var bundle = ""
        if let cf: CFString = readProp(id, kAudioProcessPropertyBundleID, "" as CFString) { bundle = cf as String }
        return ProcessInfo2(pid: pid, bundle: bundle, input: input != 0)
    }
}

protocol Source { func activeCallApp() -> String? }

struct CoreAudioSource: Source {
    func activeCallApp() -> String? {
        for p in audioProcesses() where p.input {
            if let name = callApps[p.bundle] { return name }
        }
        return nil
    }
}

/// Test source: "<seconds> <bundle-id> on|off" lines, applied by time since start.
final class FakeSource: Source {
    let lines: [(Double, String, Bool)]
    let start = Date()
    init(path: String) {
        let text = (try? String(contentsOfFile: path, encoding: .utf8)) ?? ""
        lines = text.split(separator: "\n").compactMap { l in
            let f = l.split(separator: " ")
            guard f.count == 3, let t = Double(f[0]) else { return nil }
            return (t, String(f[1]), f[2] == "on")
        }
    }
    func activeCallApp() -> String? {
        let now = Date().timeIntervalSince(start)
        var on: [String: Bool] = [:]
        for (t, b, v) in lines where t <= now { on[b] = v }
        for (b, v) in on where v { if let name = callApps[b] { return name } }
        return nil
    }
}

// MARK: - the folder orch reads

let iso: ISO8601DateFormatter = { let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime]; return f }()

final class Home {
    let url: URL
    let wanted: URL
    init() {
        if let h = ProcessInfo.processInfo.environment["ORCH_COMPANION_HOME"], !h.isEmpty {
            url = URL(fileURLWithPath: h)
        } else {
            url = FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Application Support/orch Companion")
        }
        wanted = url.appendingPathComponent("wanted")
        for d in [url, wanted] {
            try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true,
                                                     attributes: [.posixPermissions: 0o700])
            chmod(d.path, 0o700)
        }
    }

    /// A workspace wants calls while one wanted file is fresh; files older than a day are removed.
    func isWanted() -> Bool {
        let fm = FileManager.default
        let now = Date()
        var fresh = false
        for name in (try? fm.contentsOfDirectory(atPath: wanted.path)) ?? [] where name.hasSuffix(".json") {
            let p = wanted.appendingPathComponent(name).path
            guard let a = try? fm.attributesOfItem(atPath: p), (a[.type] as? FileAttributeType) == .typeRegular,
                  let m = a[.modificationDate] as? Date else { continue }
            let age = now.timeIntervalSince(m)
            if age < wantedFresh { fresh = true } else if age > wantedForget { try? fm.removeItem(atPath: p) }
        }
        return fresh
    }

    func write(_ obj: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys]) else { return }
        let tmp = url.appendingPathComponent(".now.json.part")
        let dst = url.appendingPathComponent("now.json")
        FileManager.default.createFile(atPath: tmp.path, contents: data, attributes: [.posixPermissions: 0o600])
        _ = rename(tmp.path, dst.path)
    }
}

// MARK: - the job

final class Watcher {
    let home = Home()
    let source: Source
    var detector = Detector()
    var wanted = false
    var lastWrite = Date.distantPast
    let instance = UUID().uuidString.prefix(8).lowercased()
    var onChange: ((String) -> Void)?

    init(source: Source) { self.source = source }

    var stateWord: String {
        if !wanted { return "inactive" }
        if case .call = detector.state { return "call" }
        return "idle"
    }

    var menuWords: String {
        switch detector.state {
        case .call(let app, let since) where wanted:
            let f = DateFormatter(); f.dateFormat = "HH:mm"
            return "Call in \(app) since \(f.string(from: Date(timeIntervalSince1970: since)))"
        default:
            return wanted ? "Watching for calls" : "Idle: no workspace uses it now"
        }
    }

    func tick() {
        let now = Date()
        var changed = false
        let w = home.isWanted()
        if w != wanted { wanted = w; changed = true; if !w { detector = Detector() } }
        if wanted { changed = detector.step(now: now.timeIntervalSince1970, active: source.activeCallApp()) || changed }
        if changed || now.timeIntervalSince(lastWrite) >= heartbeat {
            var obj: [String: Any] = ["v": 1, "state": stateWord, "updated": iso.string(from: now),
                                      "instance": String(instance), "pid": Int(getpid())]
            if wanted, case .call(let app, let since) = detector.state {
                obj["app"] = app
                obj["observed_since"] = iso.string(from: Date(timeIntervalSince1970: since))
            }
            home.write(obj)
            lastWrite = now
            if changed { onChange?(menuWords) }
        }
    }

    func start() {
        tick()
        Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in self?.tick() }
    }
}

final class MenuApp: NSObject, NSApplicationDelegate {
    let watcher: Watcher
    var item: NSStatusItem!
    let status = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    init(watcher: Watcher) { self.watcher = watcher }

    func applicationDidFinishLaunching(_ n: Notification) {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let img = NSImage(systemSymbolName: "waveform", accessibilityDescription: "orch Companion") {
            item.button?.image = img
        } else {
            item.button?.title = "orch"
        }
        let menu = NSMenu()
        let name = NSMenuItem(title: "orch Companion", action: nil, keyEquivalent: "")
        let line = NSMenuItem(title: fixedLine, action: nil, keyEquivalent: "")
        for m in [name, line, status] { m.isEnabled = false; menu.addItem(m) }
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Quit orch Companion", action: #selector(NSApplication.terminate(_:)),
                                keyEquivalent: "q"))
        item.menu = menu
        watcher.onChange = { [weak self] w in self?.status.title = w }
        watcher.start()
        status.title = watcher.menuWords
    }
}

// MARK: - start

let args = CommandLine.arguments
if args.contains("--selftest") { exit(selftest()) }
if let i = args.firstIndex(of: "--diagnose") {
    let secs = (i + 1 < args.count ? Int(args[i + 1]) : nil) ?? 30
    for _ in 0..<secs {
        let rows = audioProcesses()
        print("\(iso.string(from: Date())) \(rows.count) audio processes")
        for p in rows { print("  pid \(p.pid) \(p.bundle.isEmpty ? "-" : p.bundle) mic \(p.input ? "ON" : "off")") }
        fflush(stdout)
        Thread.sleep(forTimeInterval: 1)
    }
    exit(0)
}
var source: Source = CoreAudioSource()
if let i = args.firstIndex(of: "--fake-input"), i + 1 < args.count { source = FakeSource(path: args[i + 1]) }
let watcher = Watcher(source: source)
if args.contains("--headless") {
    signal(SIGTERM) { _ in exit(0) }
    watcher.start()
    RunLoop.main.run()
} else {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    let delegate = MenuApp(watcher: watcher)
    app.delegate = delegate
    app.run()
}
