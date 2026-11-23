// orch Companion: the workspaces on this Mac (ORCH-1722, menu draft C picked by the owner on 23 Nov 2026).
//
// The menu lists every orch workspace set up on this Mac, grouped by Running / Partly running / Stopped; one click
// opens a running one's dashboard or starts a stopped one ("Start the rest" for a partly running one). One
// "Start with my Mac" submenu holds the per-workspace switches (off by default).
//
// Companion never reads orch's files and never starts a process of a workspace itself: it runs the hidden
// `orch workspace companion list|start|switch|at-login` (JSON only, orch PR 2698) and shows the answer. It never
// stops anything, never runs `orch update`, never touches any other background job, and shows only orch's own
// fixed words (never raw output). The orch program is looked for in fixed folders and run without a shell.

import AppKit
import Foundation
import ServiceManagement

func companionStartsWithMac() -> Bool { SMAppService.mainApp.status == .enabled }

// MARK: - what orch answers

struct WorkspaceRow: Equatable {
    let id: String
    let name: String
    let state: String  // running | partly | stopped | nothing_to_run | unknown
    let dashboard: URL?
    let startWithMac: Bool
    let protectedFolder: Bool
}

enum WorkspaceList: Equatable {
    case loading
    case ok([WorkspaceRow], at: Date)
    case missing                  // no orch program found
    case tooOld                   // orch answered, but not this command
    case noAnswer(last: [WorkspaceRow], at: Date?)  // timed out or failed; the last good list stays, dimmed
}

/// Only http to this computer, a port, no user part (the same rule as orch's own local_url).
func localDashboard(_ s: Any?) -> URL? {
    guard let s = s as? String, s.count <= 200, let u = URLComponents(string: s), u.scheme == "http",
          u.user == nil, u.password == nil, let host = u.host, host == "127.0.0.1" || host == "localhost",
          let port = u.port, (1...65535).contains(port), u.fragment == nil, u.query == nil else { return nil }
    return u.url
}

func parseWorkspaceList(_ data: Data) -> [WorkspaceRow]? {
    guard let o = try? JSONSerialization.jsonObject(with: data) as? [String: Any], o["v"] as? Int == 1,
          o["ok"] as? Bool == true, let rows = o["workspaces"] as? [[String: Any]] else { return nil }
    return rows.compactMap { r in
        guard let id = r["id"] as? String, id.count == 32, let name = r["name"] as? String,
              let state = r["state"] as? String else { return nil }
        return WorkspaceRow(id: id, name: String(name.prefix(80)), state: state,
                            dashboard: localDashboard(r["dashboard_url"]),
                            startWithMac: r["start_with_mac"] as? Bool ?? false,
                            protectedFolder: r["protected_folder"] as? Bool ?? false)
    }
}

// MARK: - running orch

/// The orch program: ORCH_COMPANION_ORCH (tests), else the installer's folders in a fixed order.
func findOrch(env: [String: String] = ProcessInfo.processInfo.environment) -> URL? {
    let home = FileManager.default.homeDirectoryForCurrentUser.path
    var list = ["\(home)/.local/bin/orch", "/opt/homebrew/bin/orch", "/usr/local/bin/orch"]
    if let t = env["ORCH_COMPANION_ORCH"], !t.isEmpty { list = [t] }
    return list.map { URL(fileURLWithPath: $0) }.first { FileManager.default.isExecutableFile(atPath: $0.path) }
}

struct OrchAnswer { let json: [String: Any]?; let timedOut: Bool; let exit: Int32 }

/// Runs `orch workspace companion <args>` with a small environment (its own folder first on PATH, no shell, stdin
/// closed, the home folder as working folder). `timeout` nil: never killed (a start runs to its end).
func runOrch(_ orch: URL, _ args: [String], timeout: TimeInterval?) -> OrchAnswer {
    let p = Process()
    p.executableURL = orch
    p.arguments = ["workspace", "companion"] + args
    let home = FileManager.default.homeDirectoryForCurrentUser
    let mine = ProcessInfo.processInfo.environment
    var env: [String: String] = [
        "HOME": home.path,
        "PATH": ([orch.deletingLastPathComponent().path, "\(home.path)/.local/bin", "/opt/homebrew/bin",
                  "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]).joined(separator: ":"),
        "LANG": "en_US.UTF-8",
    ]
    for k in ["USER", "LOGNAME", "TMPDIR", "ORCH_HOME", "ORCH_HOME_STRICT"] { if let v = mine[k] { env[k] = v } }
    p.environment = env
    p.currentDirectoryURL = home
    p.standardInput = FileHandle.nullDevice
    let out = Pipe()
    p.standardOutput = out
    p.standardError = FileHandle.nullDevice  // never shown, never kept
    var data = Data()
    let lock = NSLock()
    out.fileHandleForReading.readabilityHandler = { h in
        let d = h.availableData
        lock.lock(); if data.count < 1_000_000 { data.append(d) }; lock.unlock()
    }
    do { try p.run() } catch { return OrchAnswer(json: nil, timedOut: false, exit: -1) }
    let done = DispatchSemaphore(value: 0)
    p.terminationHandler = { _ in done.signal() }
    if let t = timeout, done.wait(timeout: .now() + t) == .timedOut {
        p.terminate()  // only the list asks with a time limit; it starts nothing
        out.fileHandleForReading.readabilityHandler = nil
        return OrchAnswer(json: nil, timedOut: true, exit: -1)
    } else if timeout == nil {
        done.wait()
    }
    out.fileHandleForReading.readabilityHandler = nil
    lock.lock(); data.append(out.fileHandleForReading.readDataToEndOfFile()); lock.unlock()
    let line = data.split(separator: UInt8(ascii: "\n")).last.map { Data($0) } ?? Data()
    let json = (try? JSONSerialization.jsonObject(with: line)) as? [String: Any]
    return OrchAnswer(json: json, timedOut: false, exit: p.terminationStatus)
}

// MARK: - the menu model (pure: tests print it with --print-workspace-menu)

enum RowKind: Equatable { case header, label, action, warning, separator, submenuStart, submenuEnd }

struct MenuRow: Equatable {
    var kind: RowKind
    var title: String
    var detail: String = ""     // the action word at the right ("Open dashboard", "Start now", "Start the rest")
    var action: String = ""     // open:<id> start:<id> switch:<id> login-on install update retry fix:<id> more
    var checked: Bool = false
    var enabled: Bool = true
    var dot: String = ""        // running | partly | stopped
    var dim: Bool = false       // the last list while orch does not answer
}

let maxRows = 10

func workspaceMenu(_ list: WorkspaceList, starting: Set<String>, loginItemOn: Bool, result: String?,
                   now: Date = Date()) -> [MenuRow] {
    var out: [MenuRow] = [MenuRow(kind: .separator, title: "")]
    let f = DateFormatter(); f.dateFormat = "HH:mm"
    if let r = result { out.append(MenuRow(kind: .label, title: r, enabled: false)) }
    var rows: [WorkspaceRow] = []
    var dim = false
    switch list {
    case .loading:
        out.append(MenuRow(kind: .label, title: "Looking for your workspaces…", enabled: false))
        return out
    case .missing:
        out.append(MenuRow(kind: .warning, title: "orch is not installed on this Mac", enabled: false))
        out.append(MenuRow(kind: .action, title: "How to install…", action: "install"))
        return out
    case .tooOld:
        out.append(MenuRow(kind: .warning, title: "orch is too old for this list", enabled: false))
        out.append(MenuRow(kind: .action, title: "Update orch…", action: "update"))
        return out
    case .noAnswer(let last, let at):
        out.append(MenuRow(kind: .warning, title: "Couldn't reach your workspaces", enabled: false))
        out.append(MenuRow(kind: .action, title: "Try again", action: "retry"))
        guard let at = at, !last.isEmpty else { return out }
        out.append(MenuRow(kind: .header, title: "As of \(f.string(from: at))", enabled: false))
        rows = last
        dim = true
    case .ok(let r, _):
        rows = r
    }
    if rows.isEmpty {
        out.append(MenuRow(kind: .label, title: "No orch workspace on this Mac yet", enabled: false))
        return out
    }
    let up = rows.filter { $0.state == "running" }.count
    if !dim {
        out.append(MenuRow(kind: .label, title: "\(up) of \(rows.count) workspace\(rows.count == 1 ? "" : "s") running",
                           enabled: false))
    }
    let groups: [(String, String)] = [("running", "Running"), ("partly", "Partly running"), ("stopped", "Stopped"),
                                      ("unknown", "Not known")]
    var shown = 0
    var more: [MenuRow] = []
    for (key, label) in groups {
        let g = rows.filter { ($0.state == "nothing_to_run" ? "stopped" : $0.state) == key }
        if g.isEmpty { continue }
        var group: [MenuRow] = []
        for w in g {
            var row = MenuRow(kind: .action, title: w.name, enabled: !dim, dot: key, dim: dim)
            if starting.contains(w.id) {
                row.detail = "Starting…"; row.enabled = false
            } else if key == "running" {
                row.detail = w.dashboard == nil ? "" : "Open dashboard"
                row.action = w.dashboard == nil ? "" : "open:\(w.id)"
            } else if key == "partly" {
                row.detail = "Start the rest"; row.action = "start:\(w.id)"
            } else if key == "stopped" && w.state != "nothing_to_run" {
                row.detail = "Start now"; row.action = "start:\(w.id)"
            }
            if row.action.isEmpty { row.enabled = false }
            if dim { row.detail = ""; row.enabled = false }
            group.append(row)
        }
        if shown >= maxRows { more += group; continue }
        out.append(MenuRow(kind: .header, title: label, enabled: false))
        for r in group {
            if shown < maxRows { out.append(r); shown += 1 } else { more.append(r) }
        }
    }
    if !more.isEmpty {
        out.append(MenuRow(kind: .submenuStart, title: "More…", detail: "\(more.count)"))
        out += more
        out.append(MenuRow(kind: .submenuEnd, title: ""))
    }
    if dim { return out }
    // one place for the switches
    let on = rows.filter { $0.startWithMac }.count
    out.append(MenuRow(kind: .separator, title: ""))
    out.append(MenuRow(kind: .submenuStart, title: "Start with my Mac",
                       detail: !loginItemOn ? "Off" : on == 0 ? "Off" : "\(on) on"))
    if !loginItemOn {
        out.append(MenuRow(kind: .warning, title: "Needs orch Companion to start with your Mac", enabled: false))
        out.append(MenuRow(kind: .action, title: "Start orch Companion with my Mac", action: "login-on"))
        out.append(MenuRow(kind: .separator, title: ""))
    }
    for w in rows {
        out.append(MenuRow(kind: .action, title: w.name, action: "switch:\(w.id)", checked: w.startWithMac,
                           enabled: loginItemOn))
        if w.protectedFolder {
            out.append(MenuRow(kind: .warning, title: "\(w.name) may not start after login", enabled: false))
            out.append(MenuRow(kind: .action, title: "How to fix…", action: "fix:\(w.id)", enabled: loginItemOn))
        }
    }
    out.append(MenuRow(kind: .submenuEnd, title: ""))
    return out
}

/// One line after the login start: what orch said, in orch's own fixed words or counted here.
func loginResultLine(_ json: [String: Any]?, names: [String: String]) -> String? {
    guard let j = json, j["already"] as? Bool != true else { return nil }
    if j["ok"] as? Bool == false, j["results"] == nil { return j["message"] as? String }
    let results = j["results"] as? [[String: Any]] ?? []
    let failed = results.filter { $0["ok"] as? Bool == false }.compactMap { $0["id"] as? String }
    let started = results.filter { $0["ok"] as? Bool == true && !(($0["started"] as? [Any]) ?? []).isEmpty }.count
    if let first = failed.first {
        let n = names[first] ?? "a workspace"
        return failed.count == 1 ? "Could not start \(n)" : "Could not start \(n) and \(failed.count - 1) more"
    }
    if started == 0 { return nil }
    return "Started \(started) workspace\(started == 1 ? "" : "s") with your Mac"
}

// MARK: - the live part

final class Workspaces: NSObject, NSMenuDelegate {
    var list: WorkspaceList = .loading
    var starting: Set<String> = []
    var result: String?
    var onChange: (() -> Void)?
    private var lastGood: ([WorkspaceRow], Date)?
    private var busy = false
    private var timer: Timer?
    private let q = DispatchQueue(label: "orch.companion.workspaces")

    func start() {
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.refresh() }
        // once per boot (orch keeps the boot): a Companion restart or update starts nothing again
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in self?.loginStart() }
    }

    func menuWillOpen(_ menu: NSMenu) { refresh() }

    func refresh() {
        guard !busy else { return }
        busy = true
        let last = lastGood
        q.async { [weak self] in
            let next: WorkspaceList
            if let orch = findOrch() {
                let a = runOrch(orch, ["list"], timeout: 10)
                if let j = a.json, let data = try? JSONSerialization.data(withJSONObject: j),
                   let rows = parseWorkspaceList(data) {
                    next = .ok(rows, at: Date())
                } else if a.timedOut || a.json != nil {
                    next = .noAnswer(last: last?.0 ?? [], at: last?.1)
                } else {
                    next = a.exit == 2 ? .tooOld : .noAnswer(last: last?.0 ?? [], at: last?.1)
                }
            } else {
                next = .missing
            }
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.busy = false
                if case .ok(let rows, let at) = next {
                    self.lastGood = (rows, at)
                    self.starting.subtract(rows.filter { $0.state == "running" }.map { $0.id })
                }
                if self.list != next { self.list = next; self.onChange?() }
            }
        }
    }

    private func rows() -> [WorkspaceRow] {
        if case .ok(let r, _) = list { return r }
        return []
    }

    func startWorkspace(_ id: String) {
        guard let orch = findOrch() else { return }
        starting.insert(id)
        onChange?()
        q.async { [weak self] in
            let a = runOrch(orch, ["start", id], timeout: nil)
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.starting.remove(id)
                if a.json?["ok"] as? Bool == false {
                    let n = self.rows().first { $0.id == id }?.name ?? "the workspace"
                    self.result = "Could not start \(n)"
                }
                self.refresh()
            }
        }
    }

    func setSwitch(_ id: String, _ on: Bool) {
        guard let orch = findOrch() else { return }
        q.async { [weak self] in
            _ = runOrch(orch, ["switch", id, on ? "on" : "off"], timeout: 10)
            DispatchQueue.main.async { self?.refresh() }
        }
    }

    func loginStart() {
        guard let orch = findOrch() else { return }
        q.async { [weak self] in
            let a = runOrch(orch, ["at-login"], timeout: nil)
            DispatchQueue.main.async {
                guard let self = self else { return }
                let names = Dictionary(self.rows().map { ($0.id, $0.name) }, uniquingKeysWith: { a, _ in a })
                if let line = loginResultLine(a.json, names: names) { self.result = line }
                self.refresh()
            }
        }
    }

    func open(_ id: String) {
        guard let u = rows().first(where: { $0.id == id })?.dashboard, localDashboard(u.absoluteString) != nil
        else { return }
        NSWorkspace.shared.open(u)
    }

    func explainFix(_ id: String) {
        let name = rows().first { $0.id == id }?.name ?? "This workspace"
        let a = NSAlert()
        a.messageText = "\(name) may not start after login"
        a.informativeText = "Its folder is in Documents, Desktop, Downloads or iCloud Drive. Your Mac guards these "
            + "folders, so a workspace there may be stopped from starting by itself.\n\nTo fix it, move the "
            + "workspace folder to your home folder (for example a folder named Work) and open it there once."
        a.addButton(withTitle: "OK")
        NSApp.activate(ignoringOtherApps: true)
        a.runModal()
    }

    func explainUpdate() {
        let a = NSAlert()
        a.messageText = "Update orch"
        a.informativeText = "Open Terminal and run:\n\norch update\n\nThen open this menu again."
        a.addButton(withTitle: "OK")
        NSApp.activate(ignoringOtherApps: true)
        a.runModal()
    }
}

// MARK: - drawing the rows into NSMenu items

final class WorkspaceMenuBuilder: NSObject {
    let ws: Workspaces
    var items: [NSMenuItem] = []
    init(ws: Workspaces) { self.ws = ws }

    static func dotImage(_ state: String, dim: Bool) -> NSImage? {
        let name = state == "running" ? "circle.fill" : state == "partly" ? "circle.lefthalf.filled" : "circle"
        let color: NSColor = state == "running" ? .systemGreen : state == "partly" ? .systemOrange : .secondaryLabelColor
        guard let img = NSImage(systemSymbolName: name, accessibilityDescription: state) else { return nil }
        let cfg = NSImage.SymbolConfiguration(pointSize: 9, weight: .regular)
            .applying(.init(paletteColors: [dim ? color.withAlphaComponent(0.45) : color]))
        return img.withSymbolConfiguration(cfg)
    }

    func titled(_ r: MenuRow) -> NSAttributedString {
        let s = NSMutableAttributedString(string: r.title, attributes: [.font: NSFont.menuFont(ofSize: 0)])
        if !r.detail.isEmpty {
            let p = NSMutableParagraphStyle()
            p.tabStops = [NSTextTab(textAlignment: .right, location: 300)]
            s.append(NSAttributedString(string: "\t" + r.detail, attributes: [
                .font: NSFont.menuFont(ofSize: 0),
                // an action word reads as an action (critique of draft C): accent colour, not a grey hint
                .foregroundColor: r.enabled && !r.action.isEmpty ? NSColor.controlAccentColor : .secondaryLabelColor,
            ]))
            s.addAttribute(.paragraphStyle, value: p, range: NSRange(location: 0, length: s.length))
        }
        return s
    }

    /// Replaces the workspace items in `menu` (they sit right before `anchor`).
    func install(into menu: NSMenu, before anchor: NSMenuItem, loginItemOn: Bool) {
        for i in items { menu.removeItem(i) }
        items = []
        let rows = workspaceMenu(ws.list, starting: ws.starting, loginItemOn: loginItemOn, result: ws.result)
        var stack: [NSMenu] = []
        var at = menu.index(of: anchor)
        for r in rows {
            let target = stack.last
            func add(_ m: NSMenuItem) {
                if let t = target { t.addItem(m) } else { menu.insertItem(m, at: at); at += 1; items.append(m) }
            }
            switch r.kind {
            case .separator:
                add(.separator())
            case .submenuStart:
                let m = NSMenuItem(title: r.title, action: nil, keyEquivalent: "")
                m.attributedTitle = titled(MenuRow(kind: .label, title: r.title, detail: r.detail))
                let sub = NSMenu(title: r.title)
                m.submenu = sub
                add(m)
                stack.append(sub)
            case .submenuEnd:
                _ = stack.popLast()
            case .header:
                if #available(macOS 14.0, *) { add(NSMenuItem.sectionHeader(title: r.title)) } else {
                    let m = NSMenuItem(title: r.title, action: nil, keyEquivalent: ""); m.isEnabled = false; add(m)
                }
            case .label, .warning, .action:
                let m = NSMenuItem(title: r.title, action: r.action.isEmpty ? nil : #selector(pressed(_:)),
                                   keyEquivalent: "")
                m.target = self
                m.representedObject = r.action
                m.isEnabled = r.enabled && !r.action.isEmpty
                m.attributedTitle = titled(r)
                m.state = r.checked ? .on : .off
                if r.kind == .warning {
                    m.image = NSImage(systemSymbolName: "exclamationmark.triangle.fill", accessibilityDescription: "")?
                        .withSymbolConfiguration(.init(paletteColors: [.systemOrange]))
                } else if !r.dot.isEmpty {
                    m.image = WorkspaceMenuBuilder.dotImage(r.dot, dim: r.dim)
                }
                add(m)
            }
        }
    }

    @objc func pressed(_ m: NSMenuItem) {
        guard let a = m.representedObject as? String else { return }
        let parts = a.split(separator: ":", maxSplits: 1).map(String.init)
        let id = parts.count > 1 ? parts[1] : ""
        switch parts[0] {
        case "open": ws.open(id)
        case "start": ws.startWorkspace(id)
        case "switch": ws.setSwitch(id, m.state != .on)
        case "login-on": setStartWithMac(true); ws.onChange?()
        case "install":
            if let u = URL(string: "https://github.com/severinlindenmann/orch#install") { NSWorkspace.shared.open(u) }
        case "update": ws.explainUpdate()
        case "retry": ws.refresh()
        case "fix": ws.explainFix(id)
        default: break
        }
    }
}

/// Tests: `--print-workspace-menu <json file> [login-off] [starting:<id>]` prints the rows as text lines.
func printWorkspaceMenu(_ args: [String]) -> Int32 {
    guard let path = args.first else { return 2 }
    let list: WorkspaceList
    switch path {
    case "missing": list = .missing
    case "too-old": list = .tooOld
    case "live":  // the real call: ORCH_COMPANION_ORCH or the installer's folders
        if let orch = findOrch() {
            let a = runOrch(orch, ["list"], timeout: 10)
            if let j = a.json, let d = try? JSONSerialization.data(withJSONObject: j), let rows = parseWorkspaceList(d) {
                list = .ok(rows, at: Date())
            } else {
                list = a.exit == 2 ? .tooOld : .noAnswer(last: [], at: nil)
            }
        } else {
            list = .missing
        }
    default:
        guard let d = FileManager.default.contents(atPath: path) else { return 2 }
        if args.contains("no-answer") {
            list = .noAnswer(last: parseWorkspaceList(d) ?? [], at: Date(timeIntervalSince1970: 0))
        } else if let rows = parseWorkspaceList(d) {
            list = .ok(rows, at: Date())
        } else {
            list = .tooOld
        }
    }
    let starting = Set(args.filter { $0.hasPrefix("starting:") }.map { String($0.dropFirst(9)) })
    let result = args.first { $0.hasPrefix("result:") }.map { String($0.dropFirst(7)) }
    for r in workspaceMenu(list, starting: starting, loginItemOn: !args.contains("login-off"), result: result) {
        var line = "\(r.kind)|\(r.title)"
        if !r.detail.isEmpty { line += "|\(r.detail)" }
        if !r.action.isEmpty { line += "|\(r.action)" }
        if r.checked { line += "|checked" }
        if !r.enabled { line += "|disabled" }
        print(line)
    }
    return 0
}
